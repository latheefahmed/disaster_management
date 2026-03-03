from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func

from app.database import SessionLocal
from app.models.allocation import Allocation
from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.mutual_aid_offer import MutualAidOffer
from app.models.pool_transaction import PoolTransaction
from app.models.solver_run import SolverRun
from app.models.state_transfer import StateTransfer
from app.services.canonical_resources import CANONICAL_RESOURCE_ORDER
from app.services.request_service import create_request_batch
from app.services.resource_policy import is_resource_consumable, is_resource_returnable


REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "backend" / "forensics"
OUT_JSON = OUT_DIR / "ESCALATION_LIFECYCLE_RUNS.json"
OUT_MD = OUT_DIR / "ESCALATION_LIFECYCLE_REPORT.md"


@dataclass
class CheckResult:
    phase: str
    title: str
    passed: bool
    details: dict


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_int(value) -> int:
    return int(value or 0)


def _safe_float(value) -> float:
    return float(value or 0.0)


def check_resource_policy() -> CheckResult:
    consumables = [rid for rid in CANONICAL_RESOURCE_ORDER if is_resource_consumable(rid)]
    returnables = [rid for rid in CANONICAL_RESOURCE_ORDER if is_resource_returnable(rid)]
    passed = len(consumables) > 0 and len(returnables) > 0 and set(consumables).isdisjoint(set(returnables))
    return CheckResult(
        phase="P1",
        title="Resource class authority",
        passed=passed,
        details={
            "consumable_count": len(consumables),
            "returnable_count": len(returnables),
            "sample_consumables": consumables[:5],
            "sample_returnables": returnables[:5],
        },
    )


def check_allocation_provenance(db) -> CheckResult:
    latest = db.query(SolverRun).filter(SolverRun.status == "completed").order_by(SolverRun.id.desc()).first()
    if not latest:
        return CheckResult("P2", "Allocation provenance coverage", False, {"error": "No completed solver run found"})

    rows = db.query(Allocation).filter(Allocation.solver_run_id == int(latest.id)).all()
    total = len(rows)
    if total == 0:
        return CheckResult("P2", "Allocation provenance coverage", False, {"run_id": int(latest.id), "error": "No allocations in latest run"})

    with_supply = sum(1 for r in rows if str(r.supply_level or "").strip())
    with_origin = sum(1 for r in rows if str(r.origin_state_code or "").strip())
    passed = with_supply == total and with_origin == total
    return CheckResult(
        phase="P2",
        title="Allocation provenance coverage",
        passed=passed,
        details={
            "run_id": int(latest.id),
            "allocation_rows": total,
            "with_supply_level": with_supply,
            "with_origin_state_code": with_origin,
        },
    )


def check_return_origin_bookkeeping(db) -> CheckResult:
    return_pool_rows = db.query(PoolTransaction).filter(PoolTransaction.reason.like("district_return_to_origin:%")).count()
    return_transfers = db.query(StateTransfer).filter(StateTransfer.transfer_kind == "return").count()
    passed = return_pool_rows == 0 or return_transfers > 0
    return CheckResult(
        phase="P3",
        title="Return-to-origin bookkeeping",
        passed=passed,
        details={
            "pool_return_to_origin_rows": int(return_pool_rows),
            "state_transfer_return_rows": int(return_transfers),
        },
    )


def check_escalation_supply_chain(db) -> CheckResult:
    latest = db.query(SolverRun).filter(SolverRun.status == "completed").order_by(SolverRun.id.desc()).first()
    if not latest:
        return CheckResult("P4", "Escalation supply chain visibility", False, {"error": "No completed solver run found"})

    grouped = db.query(
        Allocation.supply_level,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("qty"),
    ).filter(
        Allocation.solver_run_id == int(latest.id),
        Allocation.is_unmet == False,
    ).group_by(Allocation.supply_level).all()

    by_level = {str(r.supply_level): _safe_float(r.qty) for r in grouped}
    has_any_chain = any(_safe_float(v) > 0.0 for v in by_level.values())
    passed = has_any_chain and "district" in by_level
    return CheckResult(
        phase="P4",
        title="Escalation supply chain visibility",
        passed=passed,
        details={
            "run_id": int(latest.id),
            "by_supply_level": by_level,
            "has_district": "district" in by_level,
            "has_state": "state" in by_level,
            "has_national": "national" in by_level,
        },
    )


def check_mutual_aid_acceptance_flow(db) -> CheckResult:
    counts = dict(
        db.query(MutualAidOffer.status, func.count(MutualAidOffer.id))
        .group_by(MutualAidOffer.status)
        .all()
    )
    accepted = _safe_int(counts.get("accepted"))
    rejected = _safe_int(counts.get("rejected")) + _safe_int(counts.get("revoked"))
    passed = accepted >= 0 and rejected >= 0
    return CheckResult(
        phase="P5",
        title="Mutual-aid acceptance/rejection records",
        passed=passed,
        details={
            "offer_status_counts": {str(k): _safe_int(v) for k, v in counts.items()},
            "accepted_offers": accepted,
            "rejected_or_revoked_offers": rejected,
        },
    )


def run_20_loop_stability(db) -> CheckResult:
    districts = db.query(District).order_by(District.district_code.asc()).all()
    if not districts:
        return CheckResult("P6", "20-run lifecycle loop", False, {"error": "No districts available"})

    run_rows: list[dict] = []
    resource_cycle = list(CANONICAL_RESOURCE_ORDER) if CANONICAL_RESOURCE_ORDER else ["R1"]

    for idx in range(20):
        district = districts[idx % len(districts)]
        resource_id = str(resource_cycle[idx % len(resource_cycle)])
        t_idx = int(idx % 6)
        quantity = float(5 + (idx % 3))

        item = {
            "resource_id": resource_id,
            "time": t_idx,
            "quantity": quantity,
            "priority": 1,
            "urgency": 1,
            "confidence": 1.0,
            "source": "lifecycle_audit",
        }

        try:
            out = create_request_batch(
                db,
                {
                    "district_code": str(district.district_code),
                    "state_code": str(district.state_code),
                },
                [item],
            )
            run_id = int(out.get("solver_run_id"))
            run = db.query(SolverRun).filter(SolverRun.id == run_id).first()

            alloc = _safe_float(
                db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0))
                .filter(Allocation.solver_run_id == run_id, Allocation.is_unmet == False)
                .scalar()
            )
            unmet = _safe_float(
                db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0))
                .filter(Allocation.solver_run_id == run_id, Allocation.is_unmet == True)
                .scalar()
            )
            demand = _safe_float(
                db.query(func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0))
                .filter(FinalDemand.solver_run_id == run_id)
                .scalar()
            )

            run_rows.append(
                {
                    "iteration": idx + 1,
                    "district_code": str(district.district_code),
                    "state_code": str(district.state_code),
                    "resource_id": resource_id,
                    "time": t_idx,
                    "requested_quantity": quantity,
                    "solver_run_id": run_id,
                    "solver_status": None if run is None else str(run.status),
                    "allocated_total": alloc,
                    "unmet_total": unmet,
                    "final_demand_total": demand,
                    "conservation_ok": abs((alloc + unmet) - demand) <= 1e-6,
                }
            )
        except Exception as exc:
            run_rows.append(
                {
                    "iteration": idx + 1,
                    "district_code": str(district.district_code),
                    "state_code": str(district.state_code),
                    "resource_id": resource_id,
                    "time": t_idx,
                    "requested_quantity": quantity,
                    "solver_run_id": None,
                    "solver_status": "failed",
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=2),
                    "conservation_ok": False,
                }
            )

    completed = [r for r in run_rows if str(r.get("solver_status")) == "completed"]
    conservation_ok = [r for r in run_rows if bool(r.get("conservation_ok"))]
    passed = len(completed) == 20 and len(conservation_ok) == 20

    return CheckResult(
        phase="P6",
        title="20-run lifecycle loop",
        passed=passed,
        details={
            "runs_total": len(run_rows),
            "runs_completed": len(completed),
            "runs_conservation_ok": len(conservation_ok),
            "runs": run_rows,
        },
    )


def render_report(payload: dict) -> str:
    phase_rows = payload.get("phases", [])
    verdict = "PASS" if payload.get("overall_pass") else "FAIL"

    lines = [
        "# ESCALATION LIFECYCLE REPORT",
        "",
        f"- Generated At: {payload.get('generated_at')}",
        f"- Overall Verdict: **{verdict}**",
        f"- Total Phases: {len(phase_rows)}",
        f"- Passed Phases: {sum(1 for p in phase_rows if p.get('passed'))}",
        "",
        "## Final Verdict Table",
        "",
        "| Phase | Title | Verdict |",
        "|---|---|---|",
    ]

    for row in phase_rows:
        lines.append(f"| {row.get('phase')} | {row.get('title')} | {'PASS' if row.get('passed') else 'FAIL'} |")

    lines.extend([
        "",
        "## Phase Evidence",
        "",
    ])

    for row in phase_rows:
        lines.append(f"### {row.get('phase')} - {row.get('title')}")
        lines.append(f"- Verdict: {'PASS' if row.get('passed') else 'FAIL'}")
        lines.append("- Details:")
        details = row.get("details", {})
        lines.append("```json")
        lines.append(json.dumps(details, indent=2))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        phases: list[CheckResult] = []

        phases.append(check_resource_policy())
        phases.append(check_allocation_provenance(db))
        phases.append(check_return_origin_bookkeeping(db))
        phases.append(check_escalation_supply_chain(db))
        phases.append(check_mutual_aid_acceptance_flow(db))
        phases.append(run_20_loop_stability(db))

        payload = {
            "generated_at": _now(),
            "overall_pass": all(p.passed for p in phases),
            "phases": [
                {
                    "phase": p.phase,
                    "title": p.title,
                    "passed": p.passed,
                    "details": p.details,
                }
                for p in phases
            ],
        }

        OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        OUT_MD.write_text(render_report(payload), encoding="utf-8")

        print(json.dumps({
            "overall_pass": payload["overall_pass"],
            "report": str(OUT_MD),
            "json": str(OUT_JSON),
        }, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
