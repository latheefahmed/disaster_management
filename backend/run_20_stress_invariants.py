import json
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import time
import os

from app.database import SessionLocal
from app.models.allocation import Allocation
from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.services.canonical_resources import CANONICAL_RESOURCE_ORDER
from app.services.request_service import _start_live_solver_run


RANDOM_SEED = 42
RUNS = int(os.getenv("STRESS_RUNS", "20"))
DISTRICTS_PER_RUN = 50
PROGRESS_MD = Path("STRESS_20_INVARIANTS_PROGRESS.md")


def _sum_by_slot(rows, value_key):
    out = defaultdict(float)
    for row in rows:
        key = (str(row.district_code), str(row.resource_id), int(row.time))
        out[key] += float(getattr(row, value_key) or 0.0)
    return out


def _build_requests_for_run(db, district_rows):
    requests = []
    for d in district_rows:
        rid = random.choice(CANONICAL_RESOURCE_ORDER)
        t = random.randint(0, 29)
        qty = random.randint(5, 120)
        requests.append(
            ResourceRequest(
                district_code=str(d.district_code),
                state_code=str(d.state_code),
                resource_id=rid,
                time=t,
                quantity=float(qty),
                status="pending",
                lifecycle_state="QUEUED",
                included_in_run=0,
                queued=1,
                run_id=0,
            )
        )
    db.add_all(requests)
    db.commit()
    return len(requests)


def _prepare_isolated_stress_window(db) -> dict[str, int]:
    stale_running = db.query(SolverRun).filter(
        SolverRun.mode == "live",
        SolverRun.status == "running",
    ).all()
    for row in stale_running:
        row.status = "failed"

    pending_statuses = ["pending", "escalated_national", "escalated_state", "solving"]
    cleared_requests = db.query(ResourceRequest).filter(
        ResourceRequest.run_id == 0,
        ResourceRequest.status.in_(pending_statuses),
    ).delete(synchronize_session=False)

    db.commit()
    return {
        "stale_running_marked_failed": len(stale_running),
        "cleared_queue_requests": int(cleared_requests or 0),
    }


def _write_progress(meta: dict, rows: list[dict], status: str, current_iteration: int = 0, note: str = "") -> None:
    bar_total = max(1, int(meta.get("runs") or RUNS))
    done = len(rows)
    width = 24
    filled = int(round((done / bar_total) * width))
    bar = "[" + ("#" * filled) + ("-" * (width - filled)) + "]"

    lines = [
        "# Stress 20 Invariants Progress",
        "",
        f"- updated_at: {datetime.utcnow().isoformat()}Z",
        f"- status: {status}",
        f"- progress: {done}/{bar_total} {bar}",
        f"- current_iteration: {current_iteration}",
        f"- note: {note or '-'}",
        "",
        "## Run Log",
    ]

    if not rows:
        lines.append("- (no completed runs yet)")
    else:
        for row in rows:
            lines.append(
                "- run {iteration} completed: run_id={run_id}, allocations={allocations}, final_demands={final_demands}, requests={requests}".format(
                    iteration=int(row.get("iteration") or 0),
                    run_id=int(row.get("run_id") or 0),
                    allocations=int(row.get("allocations") or 0),
                    final_demands=int(row.get("final_demands") or 0),
                    requests=int(row.get("requests") or 0),
                )
            )

    PROGRESS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_run(db, run_id: int):
    run = db.query(SolverRun).filter(SolverRun.id == run_id).first()
    if run is None:
        raise RuntimeError(f"Run {run_id} missing")
    if run.status != "completed":
        raise RuntimeError(f"Run {run_id} not completed: {run.status}")

    allocations = db.query(Allocation).filter(Allocation.solver_run_id == run_id).all()
    demands = db.query(FinalDemand).filter(FinalDemand.solver_run_id == run_id).all()

    if not demands:
        raise RuntimeError(f"Run {run_id} has no final demand rows")

    if any(int(row.time) < 0 or int(row.time) > 29 for row in demands):
        raise RuntimeError(f"Run {run_id} has final demand outside time range 0..29")

    demand_by_slot = defaultdict(float)
    for row in demands:
        key = (str(row.district_code), str(row.resource_id), int(row.time))
        demand_by_slot[key] += float(row.demand_quantity or 0.0)

    alloc_by_slot = _sum_by_slot([a for a in allocations if not bool(a.is_unmet)], "allocated_quantity")
    unmet_by_slot = _sum_by_slot([a for a in allocations if bool(a.is_unmet)], "allocated_quantity")

    for key, demand_value in demand_by_slot.items():
        lhs = alloc_by_slot.get(key, 0.0) + unmet_by_slot.get(key, 0.0)
        if abs(lhs - demand_value) > 1e-6:
            raise RuntimeError(
                f"Run {run_id} conservation failed for slot {key}: allocated+unmet={lhs}, demand={demand_value}"
            )

    slot_flags = {
        (str(a.district_code), str(a.resource_id), int(a.time)): bool(a.is_unmet)
        for a in allocations
    }

    req_rows = db.query(ResourceRequest).filter(ResourceRequest.run_id == run_id).all()
    for req in req_rows:
        if req.status in {"allocated", "unmet"}:
            key = (str(req.district_code), str(req.resource_id), int(req.time))
            if key not in slot_flags:
                raise RuntimeError(
                    f"Run {run_id} request status mismatch: request {req.id} is {req.status} without allocation slot"
                )
            if req.status == "allocated" and slot_flags[key]:
                raise RuntimeError(
                    f"Run {run_id} request status mismatch: request {req.id} allocated but slot is unmet"
                )
            if req.status == "unmet" and not slot_flags[key]:
                raise RuntimeError(
                    f"Run {run_id} request status mismatch: request {req.id} unmet but slot is allocated"
                )

    return {
        "run_id": run_id,
        "allocations": len(allocations),
        "final_demands": len(demands),
        "requests": len(req_rows),
        "sum_allocated": round(sum(float(a.allocated_quantity or 0.0) for a in allocations if not bool(a.is_unmet)), 4),
        "sum_unmet": round(sum(float(a.allocated_quantity or 0.0) for a in allocations if bool(a.is_unmet)), 4),
        "sum_final_demand": round(sum(float(d.demand_quantity or 0.0) for d in demands), 4),
    }


def _wait_for_run_completion(db, run_id: int, timeout_sec: int = 900) -> str:
    started = time.perf_counter()
    while True:
        with SessionLocal() as probe_db:
            run = probe_db.query(SolverRun).filter(SolverRun.id == int(run_id)).first()
            status = str(getattr(run, "status", "") or "")
        if status in {"completed", "failed", "failed_reconciliation"}:
            return status
        if (time.perf_counter() - started) >= float(timeout_sec):
            return status or "timeout"
        time.sleep(1.0)


def main():
    random.seed(RANDOM_SEED)
    db = SessionLocal()
    report_rows = []
    meta = {}
    try:
        districts = db.query(District).order_by(District.district_code.asc()).all()
        if not districts:
            raise RuntimeError("No districts available")

        sampled_count = min(DISTRICTS_PER_RUN, len(districts))
        meta["districts_available"] = len(districts)
        meta["districts_per_run"] = sampled_count
        meta["runs"] = RUNS
        meta["seed"] = RANDOM_SEED
        meta["isolation_prep"] = _prepare_isolated_stress_window(db)
        _write_progress(meta, report_rows, status="running", current_iteration=0, note="Initialized stress run")

        for i in range(1, RUNS + 1):
            _write_progress(meta, report_rows, status="running", current_iteration=i, note="Starting solver run")
            chosen = random.sample(districts, sampled_count)
            inserted = _build_requests_for_run(db, chosen)
            run_id = _start_live_solver_run(db)
            terminal_status = _wait_for_run_completion(db, int(run_id), timeout_sec=900)
            if terminal_status != "completed":
                _write_progress(
                    meta,
                    report_rows,
                    status="failed",
                    current_iteration=i,
                    note=f"Run {run_id} terminal status={terminal_status}",
                )
                raise RuntimeError(f"Run {run_id} did not complete successfully: {terminal_status}")
            summary = _validate_run(db, int(run_id))
            summary["iteration"] = i
            summary["inserted_requests"] = inserted
            report_rows.append(summary)
            print("STRESS_RUN", summary)
            _write_progress(meta, report_rows, status="running", current_iteration=i, note=f"Run {run_id} completed")

        output = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "meta": meta,
            "result": "pass",
            "runs": report_rows,
        }
        _write_progress(meta, report_rows, status="pass", current_iteration=RUNS, note="All runs completed")
    except Exception as exc:
        output = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "meta": meta,
            "result": "fail",
            "error": str(exc),
            "runs": report_rows,
        }
        _write_progress(meta, report_rows, status="fail", current_iteration=len(report_rows), note=str(exc))
        raise
    finally:
        out_path = Path("forensics") / "phase7_20run_stress_report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        db.close()


if __name__ == "__main__":
    main()
