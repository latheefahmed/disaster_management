import json
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path

import pandas as pd
from sqlalchemy import func

from app.config import PHASE4_RESOURCE_DATA
from app.database import SessionLocal
from app.models.allocation import Allocation
from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.request import ResourceRequest
from app.models.resource import Resource
from app.models.scenario import Scenario
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.scenario_request import ScenarioRequest
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.solver_run import SolverRun
from app.routers.district import get_allocations_for_district
from app.services.allocation_service import get_latest_completed_run
from app.services.request_service import create_request_batch, escalate_request_to_national, trigger_live_solver_run
from app.services.scenario_runner import run_scenario


@dataclass
class Candidate:
    district_code: str
    state_code: str
    resource_id: str
    district_stock: float
    state_stock: float
    national_stock: float


def load_stock_maps():
    district_df = pd.read_csv(PHASE4_RESOURCE_DATA / "district_resource_stock.csv")
    state_df = pd.read_csv(PHASE4_RESOURCE_DATA / "state_resource_stock.csv")
    national_df = pd.read_csv(PHASE4_RESOURCE_DATA / "national_resource_stock.csv")

    district_df["district_code"] = district_df["district_code"].astype(str)
    district_df["resource_id"] = district_df["resource_id"].astype(str)
    state_df["state_code"] = state_df["state_code"].astype(str)
    state_df["resource_id"] = state_df["resource_id"].astype(str)
    national_df["resource_id"] = national_df["resource_id"].astype(str)

    district_agg = district_df.groupby(["district_code", "resource_id"], as_index=False)["quantity"].sum()
    state_agg = state_df.groupby(["state_code", "resource_id"], as_index=False)["quantity"].sum()
    national_agg = national_df.groupby(["resource_id"], as_index=False)["quantity"].sum()

    district_stock = {(str(r.district_code), str(r.resource_id)): float(r.quantity) for r in district_agg.itertuples(index=False)}
    state_stock = {(str(r.state_code), str(r.resource_id)): float(r.quantity) for r in state_agg.itertuples(index=False)}
    national_stock = {str(r.resource_id): float(r.quantity) for r in national_agg.itertuples(index=False)}

    return district_stock, state_stock, national_stock


def select_candidates(db):
    district_stock, state_stock, national_stock = load_stock_maps()
    districts = db.query(District).all()

    candidates: list[Candidate] = []
    for d in districts:
        district_code = str(d.district_code)
        state_code = str(d.state_code)
        resources = {r for (dc, r) in district_stock.keys() if dc == district_code}
        for r in resources:
            ds = float(district_stock.get((district_code, r), 0.0))
            ss = float(state_stock.get((state_code, r), 0.0))
            ns = float(national_stock.get(r, 0.0))
            candidates.append(Candidate(district_code, state_code, r, ds, ss, ns))

    def first_where(predicate):
        for c in candidates:
            if predicate(c):
                return c
        return None

    chosen = {
        "district_only": first_where(lambda c: c.district_stock > 0),
        "state_only": first_where(lambda c: c.district_stock <= 0 and c.state_stock > 0),
        "national_only": first_where(lambda c: c.district_stock <= 0 and c.state_stock <= 0 and c.national_stock > 0),
        "district_state": first_where(lambda c: c.district_stock > 0 and c.state_stock > 0),
        "district_national": first_where(lambda c: c.district_stock > 0 and c.national_stock > 0),
        "full_shortage": first_where(lambda c: c.district_stock > 0),
    }
    return chosen


def run_slot_metrics(db, run_id: int, district_code: str, resource_id: str, time_idx: int):
    final_q = float(
        db.query(func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0))
        .filter(
            FinalDemand.solver_run_id == run_id,
            FinalDemand.district_code == district_code,
            FinalDemand.resource_id == resource_id,
            FinalDemand.time == time_idx,
        )
        .scalar()
        or 0.0
    )

    rows = db.query(
        Allocation.supply_level,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("qty"),
    ).filter(
        Allocation.solver_run_id == run_id,
        Allocation.district_code == district_code,
        Allocation.resource_id == resource_id,
        Allocation.time == time_idx,
        Allocation.is_unmet == False,
    ).group_by(Allocation.supply_level).all()

    by_level = {str(r.supply_level): float(r.qty or 0.0) for r in rows}
    district_alloc = float(by_level.get("district", 0.0))
    state_alloc = float(by_level.get("state", 0.0))
    national_alloc = float(by_level.get("national", 0.0))

    unmet_q = float(
        db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0))
        .filter(
            Allocation.solver_run_id == run_id,
            Allocation.district_code == district_code,
            Allocation.resource_id == resource_id,
            Allocation.time == time_idx,
            Allocation.is_unmet == True,
        )
        .scalar()
        or 0.0
    )

    alloc_total = district_alloc + state_alloc + national_alloc
    return {
        "final": final_q,
        "district_alloc": district_alloc,
        "state_alloc": state_alloc,
        "national_alloc": national_alloc,
        "alloc_total": alloc_total,
        "unmet": unmet_q,
        "conservation_ok": abs((alloc_total + unmet_q) - final_q) <= 1e-6,
    }


def run_scenario_case(db, name: str, candidate: Candidate, demand: float, state_override: float, national_override: float, time_idx: int = 0):
    scenario = Scenario(name=name)
    db.add(scenario)
    db.commit()
    db.refresh(scenario)

    db.add(ScenarioRequest(
        scenario_id=int(scenario.id),
        district_code=candidate.district_code,
        state_code=candidate.state_code,
        resource_id=candidate.resource_id,
        time=int(time_idx),
        quantity=float(demand),
    ))
    db.add(ScenarioStateStock(
        scenario_id=int(scenario.id),
        state_code=candidate.state_code,
        resource_id=candidate.resource_id,
        quantity=float(state_override),
    ))
    db.add(ScenarioNationalStock(
        scenario_id=int(scenario.id),
        resource_id=candidate.resource_id,
        quantity=float(national_override),
    ))
    db.commit()

    run_scenario(db, int(scenario.id))
    run = db.query(SolverRun).filter(SolverRun.scenario_id == int(scenario.id)).order_by(SolverRun.id.desc()).first()
    metrics = run_slot_metrics(db, int(run.id), candidate.district_code, candidate.resource_id, int(time_idx))

    return {
        "scenario_id": int(scenario.id),
        "run_id": int(run.id),
        "run_status": str(run.status),
        "district_code": candidate.district_code,
        "state_code": candidate.state_code,
        "resource_id": candidate.resource_id,
        "csv_stock": {
            "district_stock": float(candidate.district_stock),
            "state_stock": float(candidate.state_stock),
            "national_stock": float(candidate.national_stock),
        },
        "input": {
            "demand": float(demand),
            "state_override": float(state_override),
            "national_override": float(national_override),
            "time": int(time_idx),
        },
        "metrics": metrics,
    }


def with_all_human_only(db):
    rows = db.query(District).all()
    backup = {str(r.district_code): str(r.demand_mode or "baseline_plus_human") for r in rows}
    for r in rows:
        r.demand_mode = "human_only"
    db.commit()
    return backup


def restore_modes(db, backup):
    rows = db.query(District).all()
    for r in rows:
        r.demand_mode = backup.get(str(r.district_code), "baseline_plus_human")
    db.commit()


def run_live_determinism(db):
    d = db.query(District).filter(District.district_code == "603").first()
    if d is None:
        d = db.query(District).first()
    if d is None:
        raise RuntimeError("No district found for live determinism test")

    out = create_request_batch(
        db,
        {"district_code": str(d.district_code), "state_code": str(d.state_code)},
        [{
            "resource_id": "R1",
            "time": 0,
            "quantity": 10,
            "priority": 1,
            "urgency": 1,
            "confidence": 1.0,
            "source": "human",
        }],
    )
    run_id = int(out["solver_run_id"])
    run = db.query(SolverRun).filter(SolverRun.id == run_id).first()

    final_count = int(db.query(func.count(FinalDemand.id)).filter(FinalDemand.solver_run_id == run_id).scalar() or 0)
    alloc_count = int(db.query(func.count(Allocation.id)).filter(Allocation.solver_run_id == run_id).scalar() or 0)

    return {
        "run_id": run_id,
        "status": str(run.status),
        "final_demands": final_count,
        "allocations": alloc_count,
        "pass": str(run.status) == "completed" and final_count > 0 and alloc_count > 0,
    }


def run_escalation_non_blocking(db):
    d = db.query(District).filter(District.district_code == "603").first()
    if d is None:
        d = db.query(District).first()
    if d is None:
        raise RuntimeError("No district found for escalation test")

    req = ResourceRequest(
        district_code=str(d.district_code),
        state_code=str(d.state_code),
        resource_id="R1",
        time=0,
        quantity=5.0,
        priority=1,
        urgency=1,
        confidence=1.0,
        source="human",
        status="pending",
        included_in_run=0,
        queued=1,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    escalated = escalate_request_to_national(db, int(req.id), actor_state=str(d.state_code), reason="matrix-check")
    run_id = int(trigger_live_solver_run(db))

    alloc_sum = float(
        db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0))
        .filter(
            Allocation.solver_run_id == run_id,
            Allocation.district_code == str(d.district_code),
            Allocation.resource_id == "R1",
            Allocation.time == 0,
            Allocation.is_unmet == False,
        )
        .scalar()
        or 0.0
    )

    return {
        "request_id": int(req.id),
        "status_after_escalate": str(escalated.status),
        "run_id": run_id,
        "allocated_quantity": alloc_sum,
        "pass": alloc_sum > 0,
    }


def run_dashboard_binding_check(db, district_code: str):
    saved = [(int(r.id), str(r.status)) for r in db.query(SolverRun).filter(SolverRun.mode == "live", SolverRun.status == "completed").all()]
    for run_id, _ in saved:
        row = db.query(SolverRun).filter(SolverRun.id == run_id).first()
        row.status = "failed"
    db.commit()

    selected = get_latest_completed_run(db)
    rows = get_allocations_for_district(db, district_code)

    for run_id, status in saved:
        row = db.query(SolverRun).filter(SolverRun.id == run_id).first()
        row.status = status
    db.commit()

    return {
        "selected_run_id": None if selected is None else int(selected.id),
        "selected_mode": None if selected is None else str(selected.mode),
        "rows": len(rows),
        "nonzero_rows": len([r for r in rows if float(r.allocated_quantity or 0.0) > 0]),
        "pass": selected is not None and str(selected.mode) == "scenario" and len(rows) > 0,
    }


def main():
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline": {},
        "matrix": {},
        "live_run_test": {},
        "dashboard_binding_test": {},
        "escalation_non_blocking_test": {},
    }

    db = SessionLocal()
    try:
        latest_runs = db.query(SolverRun).order_by(SolverRun.id.desc()).limit(10).all()
        report["baseline"] = {
            "recent_runs": [
                {
                    "id": int(r.id),
                    "mode": str(r.mode),
                    "status": str(r.status),
                    "scenario_id": None if r.scenario_id is None else int(r.scenario_id),
                    "started_at": None if r.started_at is None else str(r.started_at),
                }
                for r in latest_runs
            ]
        }

        candidates = select_candidates(db)
        missing = [k for k, v in candidates.items() if v is None]
        report["candidate_selection"] = {
            "missing": missing,
            "selected": {k: None if v is None else {
                "district_code": v.district_code,
                "state_code": v.state_code,
                "resource_id": v.resource_id,
                "district_stock": v.district_stock,
                "state_stock": v.state_stock,
                "national_stock": v.national_stock,
            } for k, v in candidates.items()}
        }

        mode_backup = with_all_human_only(db)
        try:
            if candidates["district_only"] is not None:
                c = candidates["district_only"]
                demand = max(1.0, min(c.district_stock * 0.5, c.district_stock))
                case = run_scenario_case(db, "MATRIX_DISTRICT_ONLY", c, demand, state_override=0.0, national_override=0.0)
                m = case["metrics"]
                case["pass"] = case["run_status"] == "completed" and m["district_alloc"] > 0 and m["state_alloc"] <= 1e-6 and m["national_alloc"] <= 1e-6 and m["unmet"] <= 1e-6 and m["conservation_ok"]
                report["matrix"]["district_only"] = case

            if candidates["state_only"] is not None:
                c = candidates["state_only"]
                demand = max(1.0, min(c.state_stock * 0.1, c.state_stock))
                case = run_scenario_case(db, "MATRIX_STATE_ONLY", c, demand, state_override=c.state_stock, national_override=0.0)
                m = case["metrics"]
                case["pass"] = case["run_status"] == "completed" and m["state_alloc"] > 0 and m["district_alloc"] <= 1e-6 and m["national_alloc"] <= 1e-6 and m["unmet"] <= 1e-6 and m["conservation_ok"]
                report["matrix"]["state_only"] = case

            if candidates["national_only"] is not None:
                c = candidates["national_only"]
                demand = max(1.0, min(c.national_stock * 0.1, c.national_stock))
                case = run_scenario_case(db, "MATRIX_NATIONAL_ONLY", c, demand, state_override=0.0, national_override=c.national_stock)
                m = case["metrics"]
                case["pass"] = case["run_status"] == "completed" and m["national_alloc"] > 0 and m["district_alloc"] <= 1e-6 and m["state_alloc"] <= 1e-6 and m["unmet"] <= 1e-6 and m["conservation_ok"]
                report["matrix"]["national_only"] = case

            if candidates["district_state"] is not None:
                c = candidates["district_state"]
                delta = max(1.0, min(100.0, c.state_stock * 0.05))
                demand = c.district_stock + min(delta, c.state_stock)
                case = run_scenario_case(db, "MATRIX_DISTRICT_STATE", c, demand, state_override=c.state_stock, national_override=0.0)
                m = case["metrics"]
                case["pass"] = case["run_status"] == "completed" and m["district_alloc"] > 0 and m["state_alloc"] > 0 and m["national_alloc"] <= 1e-6 and m["unmet"] <= 1e-6 and m["conservation_ok"]
                report["matrix"]["district_state"] = case

            if candidates["district_national"] is not None:
                c = candidates["district_national"]
                delta = max(1.0, min(100.0, c.national_stock * 0.05))
                demand = c.district_stock + min(delta, c.national_stock)
                case = run_scenario_case(db, "MATRIX_DISTRICT_NATIONAL", c, demand, state_override=0.0, national_override=c.national_stock)
                m = case["metrics"]
                case["pass"] = case["run_status"] == "completed" and m["district_alloc"] > 0 and m["national_alloc"] > 0 and m["state_alloc"] <= 1e-6 and m["unmet"] <= 1e-6 and m["conservation_ok"]
                report["matrix"]["district_national"] = case

            if candidates["full_shortage"] is not None:
                c = candidates["full_shortage"]
                demand = c.district_stock + 100.0
                case = run_scenario_case(db, "MATRIX_FULL_SHORTAGE", c, demand, state_override=0.0, national_override=0.0)
                m = case["metrics"]
                case["pass"] = case["run_status"] == "completed" and m["unmet"] > 0 and m["conservation_ok"]
                report["matrix"]["full_shortage"] = case
        finally:
            restore_modes(db, mode_backup)

        report["live_run_test"] = run_live_determinism(db)
        report["escalation_non_blocking_test"] = run_escalation_non_blocking(db)

        district_for_dashboard = None
        for case in report["matrix"].values():
            district_for_dashboard = case.get("district_code")
            if district_for_dashboard:
                break
        if district_for_dashboard is None:
            district_for_dashboard = "603"

        report["dashboard_binding_test"] = run_dashboard_binding_check(db, district_for_dashboard)

        report["summary"] = {
            "matrix_pass": all(bool(v.get("pass")) for v in report["matrix"].values()) if report["matrix"] else False,
            "live_run_pass": bool(report["live_run_test"].get("pass")),
            "escalation_pass": bool(report["escalation_non_blocking_test"].get("pass")),
            "dashboard_binding_pass": bool(report["dashboard_binding_test"].get("pass")),
        }
    finally:
        db.close()

    out_path = Path("stability_matrix_results.json")
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
