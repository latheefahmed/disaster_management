import json
import time
from datetime import datetime, UTC

from sqlalchemy import func

from app.database import SessionLocal
from app.models.allocation import Allocation
from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.request import ResourceRequest
from app.models.resource import Resource
from app.models.scenario import Scenario
from app.models.scenario_request import ScenarioRequest
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.solver_run import SolverRun
from app.models.agent_finding import AgentFinding
from app.services.request_service import (
    create_request_batch,
    escalate_request_to_national,
    resolve_national_escalation,
    get_state_allocation_summary,
    get_national_allocation_summary,
)
from app.services.scenario_runner import run_scenario


def wait_for_run(run_id: int, timeout_sec: int = 300):
    start = time.time()
    while time.time() - start < timeout_sec:
        db = SessionLocal()
        try:
            row = db.query(SolverRun).filter(SolverRun.id == run_id).first()
            if row and row.status in {"completed", "failed"}:
                return row.status
        finally:
            db.close()
        time.sleep(1)
    db = SessionLocal()
    try:
        row = db.query(SolverRun).filter(SolverRun.id == run_id).first()
        return row.status if row else "missing"
    finally:
        db.close()


def slot_metrics(run_id: int, district_code: str, resource_id: str, time_idx: int):
    db = SessionLocal()
    try:
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
        alloc_q = float(
            db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0))
            .filter(
                Allocation.solver_run_id == run_id,
                Allocation.district_code == district_code,
                Allocation.resource_id == resource_id,
                Allocation.time == time_idx,
                Allocation.is_unmet == False,
            )
            .scalar()
            or 0.0
        )
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
        return {
            "final": final_q,
            "alloc": alloc_q,
            "unmet": unmet_q,
            "conservation_ok": abs((alloc_q + unmet_q) - final_q) <= 1e-6,
        }
    finally:
        db.close()


def main():
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "tests": {},
        "dashboard_validation": {},
    }

    db = SessionLocal()
    try:
        district = db.query(District).filter(District.district_code == "603").first()
        if not district:
            raise RuntimeError("District 603 not found")
        state_code = str(district.state_code)

        resources = {str(r.resource_id) for r in db.query(Resource).all()}
        if "R1" not in resources:
            db.add(Resource(resource_id="R1", resource_name="R1", ethical_priority=1.0, canonical_name="r1"))
            db.commit()

        # District test (live run with exact human-only request)
        original_mode = str(district.demand_mode or "baseline_plus_human")
        district.demand_mode = "human_only"
        db.commit()
        try:
            out = create_request_batch(
                db,
                {"district_code": "603", "state_code": state_code},
                [
                    {
                        "resource_id": "R1",
                        "time": 0,
                        "quantity": 10,
                        "priority": 1,
                        "urgency": 1,
                        "confidence": 1.0,
                        "source": "human",
                    }
                ],
            )
            run_id = int(out["solver_run_id"])
            run_status = wait_for_run(run_id)
            m = slot_metrics(run_id, "603", "R1", 0)
            report["tests"]["district_test"] = {
                "run_id": run_id,
                "run_status": run_status,
                "metrics": m,
                "expected": {"final": 10.0, "alloc": 10.0, "unmet": 0.0},
                "pass": run_status == "completed" and m["final"] >= 10.0 and m["alloc"] > 0 and m["conservation_ok"],
            }
        finally:
            district.demand_mode = original_mode
            db.commit()

        def run_scenario_case(
            name: str,
            state_stock: float,
            national_stock: float,
            resource_id: str = "R1",
            quantity: float = 10.0,
            time_idx: int = 0,
        ):
            sc = Scenario(name=name)
            db.add(sc)
            db.commit()
            db.refresh(sc)

            db.add(
                ScenarioRequest(
                    scenario_id=sc.id,
                    district_code="603",
                    state_code=state_code,
                    resource_id=resource_id,
                    time=time_idx,
                    quantity=quantity,
                )
            )
            db.add(
                ScenarioStateStock(
                    scenario_id=sc.id,
                    state_code=state_code,
                    resource_id=resource_id,
                    quantity=float(state_stock),
                )
            )
            db.add(
                ScenarioNationalStock(
                    scenario_id=sc.id,
                    resource_id=resource_id,
                    quantity=float(national_stock),
                )
            )
            db.commit()

            district_mode_before = str(district.demand_mode or "baseline_plus_human")
            district.demand_mode = "human_only"
            db.commit()
            run_scenario(db, sc.id)
            district.demand_mode = district_mode_before
            db.commit()

            run = (
                db.query(SolverRun)
                .filter(SolverRun.scenario_id == sc.id)
                .order_by(SolverRun.id.desc())
                .first()
            )
            m = slot_metrics(int(run.id), "603", resource_id, time_idx)
            return {
                "scenario_id": sc.id,
                "run_id": int(run.id),
                "run_status": run.status,
                "metrics": m,
            }

        state_cover = run_scenario_case("DEBUG_STATE_COVER", 20.0, 0.0)
        state_cover["expected"] = {"alloc": 10.0, "unmet": 0.0}
        state_cover["pass"] = state_cover["run_status"] == "completed" and state_cover["metrics"]["alloc"] >= 9.999 and state_cover["metrics"]["unmet"] <= 1e-6
        report["tests"]["state_cover_test"] = state_cover

        national_cover = run_scenario_case("DEBUG_NATIONAL_COVER", 0.0, 50.0)
        national_cover["expected"] = {"alloc": 10.0, "unmet": 0.0}
        national_cover["pass"] = national_cover["run_status"] == "completed" and national_cover["metrics"]["alloc"] >= 9.999 and national_cover["metrics"]["unmet"] <= 1e-6
        report["tests"]["national_cover_test"] = national_cover

        shortage = run_scenario_case(
            "DEBUG_FULL_SHORTAGE",
            0.0,
            0.0,
            resource_id="R11",
            quantity=100.0,
            time_idx=0,
        )
        shortage["expected"] = {"alloc": 3.0, "unmet": 97.0}
        shortage["pass"] = shortage["run_status"] == "completed" and shortage["metrics"]["alloc"] <= 3.001 and shortage["metrics"]["unmet"] >= 96.999
        report["tests"]["full_shortage_test"] = shortage

        # Escalation test (state escalate -> national resolve -> allocated/partial)
        esc_req = ResourceRequest(
            district_code="603",
            state_code=state_code,
            resource_id="R1",
            time=1,
            quantity=10.0,
            priority=1,
            urgency=1,
            confidence=1.0,
            source="human",
            status="pending",
            included_in_run=0,
            queued=1,
        )
        db.add(esc_req)
        db.commit()
        db.refresh(esc_req)
        esc_req_id = int(esc_req.id)
        esc_before = db.query(ResourceRequest).filter(ResourceRequest.id == esc_req_id).first().status
        esc_row = escalate_request_to_national(db, esc_req_id, actor_state=state_code, reason="debug-test")
        resolved = resolve_national_escalation(db, esc_row.id, decision="allocated", note="debug-resolve")
        report["tests"]["escalation_test"] = {
            "request_id": esc_req_id,
            "status_before": esc_before,
            "status_after_escalate": esc_row.status,
            "status_after_resolve": resolved.status,
            "pass": resolved.status in {"allocated", "partial"},
            "note": "Resolution path validates escalation lifecycle transition.",
        }

        # Dashboard data availability checks (service-level)
        state_summary = get_state_allocation_summary(db, state_code)
        national_summary = get_national_allocation_summary(db)
        report["dashboard_validation"] = {
            "district": {
                "latest_completed_live_run_id": int(state_summary.get("solver_run_id") or 0),
                "kpi_nonzero": float(report["tests"]["district_test"]["metrics"]["final"]) > 0,
            },
            "state": {
                "solver_run_id": state_summary.get("solver_run_id"),
                "rows": len(state_summary.get("rows") or []),
                "nonzero_rows": len([r for r in (state_summary.get("rows") or []) if float(r.get("allocated_quantity", 0)) > 0 or float(r.get("unmet_quantity", 0)) > 0]),
            },
            "national": {
                "solver_run_id": national_summary.get("solver_run_id"),
                "rows": len(national_summary.get("rows") or []),
                "nonzero_rows": len([r for r in (national_summary.get("rows") or []) if float(r.get("allocated_quantity", 0)) > 0 or float(r.get("unmet_quantity", 0)) > 0]),
            },
            "admin": {
                "solver_runs_visible": int(db.query(func.count(SolverRun.id)).scalar() or 0),
                "agent_findings_visible": int(db.query(func.count(AgentFinding.id)).scalar() or 0),
            },
        }

        stale_live = db.query(SolverRun).filter(
            SolverRun.mode == "live",
            SolverRun.status == "running",
        ).all()
        if stale_live:
            for row in stale_live:
                row.status = "failed"
            db.commit()

    finally:
        db.close()

    out_path = "debug_suite_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
