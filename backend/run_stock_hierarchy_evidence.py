import json
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
from app.models.scenario import Scenario
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.scenario_request import ScenarioRequest
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.solver_run import SolverRun
from app.services.allocation_service import get_latest_completed_run
from app.services.request_service import create_request_batch, escalate_request_to_national, trigger_live_solver_run
from app.services.scenario_runner import run_scenario


def grouped_stocks():
    district_df = pd.read_csv(PHASE4_RESOURCE_DATA / "district_resource_stock.csv")
    state_df = pd.read_csv(PHASE4_RESOURCE_DATA / "state_resource_stock.csv")
    national_df = pd.read_csv(PHASE4_RESOURCE_DATA / "national_resource_stock.csv")

    district_df["district_code"] = district_df["district_code"].astype(str)
    district_df["resource_id"] = district_df["resource_id"].astype(str)
    state_df["state_code"] = state_df["state_code"].astype(str)
    state_df["resource_id"] = state_df["resource_id"].astype(str)
    national_df["resource_id"] = national_df["resource_id"].astype(str)

    district_g = district_df.groupby(["district_code", "resource_id"], as_index=False)["quantity"].sum()
    state_g = state_df.groupby(["state_code", "resource_id"], as_index=False)["quantity"].sum()
    national_g = national_df.groupby(["resource_id"], as_index=False)["quantity"].sum()

    return district_g, state_g, national_g


def slot_breakdown(db, run_id: int, district_code: str, resource_id: str, time_idx: int):
    final_val = float(
        db.query(func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0))
        .filter(
            FinalDemand.solver_run_id == int(run_id),
            FinalDemand.district_code == str(district_code),
            FinalDemand.resource_id == str(resource_id),
            FinalDemand.time == int(time_idx),
        )
        .scalar()
        or 0.0
    )

    supply_rows = (
        db.query(Allocation.supply_level, func.coalesce(func.sum(Allocation.allocated_quantity), 0.0))
        .filter(
            Allocation.solver_run_id == int(run_id),
            Allocation.district_code == str(district_code),
            Allocation.resource_id == str(resource_id),
            Allocation.time == int(time_idx),
        )
        .group_by(Allocation.supply_level)
        .all()
    )

    by_supply = {str(k): float(v or 0.0) for k, v in supply_rows}
    alloc_val = sum(v for k, v in by_supply.items() if k != "unmet")
    unmet_val = float(by_supply.get("unmet", 0.0))

    return {
        "final": final_val,
        "allocated": alloc_val,
        "unmet": unmet_val,
        "by_supply_level": by_supply,
        "conservation_ok": abs((alloc_val + unmet_val) - final_val) <= 1e-6,
    }


def create_scenario_case(db, district: District, resource_id: str, demand_qty: float, state_qty: float, national_qty: float, name: str):
    sc = Scenario(name=name)
    db.add(sc)
    db.commit()
    db.refresh(sc)

    db.add(
        ScenarioRequest(
            scenario_id=int(sc.id),
            district_code=str(district.district_code),
            state_code=str(district.state_code),
            resource_id=str(resource_id),
            time=0,
            quantity=float(demand_qty),
        )
    )
    db.add(
        ScenarioStateStock(
            scenario_id=int(sc.id),
            state_code=str(district.state_code),
            resource_id=str(resource_id),
            quantity=float(state_qty),
        )
    )
    db.add(
        ScenarioNationalStock(
            scenario_id=int(sc.id),
            resource_id=str(resource_id),
            quantity=float(national_qty),
        )
    )
    db.commit()

    mode_before = str(district.demand_mode or "baseline_plus_human")
    district.demand_mode = "human_only"
    db.commit()
    try:
        run_scenario(db, int(sc.id))
    finally:
        district.demand_mode = mode_before
        db.commit()

    run = (
        db.query(SolverRun)
        .filter(SolverRun.scenario_id == int(sc.id))
        .order_by(SolverRun.id.desc())
        .first()
    )
    metrics = slot_breakdown(db, int(run.id), str(district.district_code), str(resource_id), 0)
    return {
        "scenario_id": int(sc.id),
        "run_id": int(run.id),
        "run_status": str(run.status),
        "district_code": str(district.district_code),
        "state_code": str(district.state_code),
        "resource_id": str(resource_id),
        "demand": float(demand_qty),
        "state_stock": float(state_qty),
        "national_stock": float(national_qty),
        "metrics": metrics,
    }


def main():
    district_g, state_g, national_g = grouped_stocks()

    db = SessionLocal()
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline": {},
        "cases": {},
        "live_run": {},
        "dashboard_fallback": {},
        "escalation_non_blocking": {},
    }

    try:
        district_map = {
            str(d.district_code): str(d.state_code)
            for d in db.query(District).all()
        }

        merged = district_g.copy()
        merged["state_code"] = merged["district_code"].map(district_map)
        merged = merged.dropna(subset=["state_code"])

        merged = merged.merge(
            state_g.rename(columns={"quantity": "state_qty"}),
            on=["state_code", "resource_id"],
            how="left",
        ).merge(
            national_g.rename(columns={"quantity": "national_qty"}),
            on=["resource_id"],
            how="left",
        )
        merged["state_qty"] = merged["state_qty"].fillna(0.0)
        merged["national_qty"] = merged["national_qty"].fillna(0.0)

        state_candidate = merged[(merged["state_qty"] > 0) & (merged["quantity"] <= merged["quantity"] + merged["state_qty"])].copy()
        if state_candidate.empty:
            raise RuntimeError("No stock candidate for state-resolution case")
        state_candidate = state_candidate.sort_values(["quantity", "state_qty"], ascending=[True, False]).iloc[0]

        district = db.query(District).filter(District.district_code == str(state_candidate["district_code"])).first()
        if district is None:
            raise RuntimeError("Candidate district not found in DB")

        district_stock = float(state_candidate["quantity"])
        state_stock = float(state_candidate["state_qty"])
        resource_id = str(state_candidate["resource_id"])

        demand_state = district_stock + min(50.0, max(1.0, state_stock * 0.000001))
        case_state = create_scenario_case(
            db,
            district=district,
            resource_id=resource_id,
            demand_qty=demand_state,
            state_qty=state_stock,
            national_qty=0.0,
            name="EVIDENCE_STATE_AUTOPULL",
        )
        report["cases"]["state_autopull"] = case_state

        national_candidate = merged[(merged["national_qty"] > 0)].copy()
        national_candidate = national_candidate.sort_values(["quantity", "state_qty", "national_qty"], ascending=[True, True, False]).iloc[0]

        district_n = db.query(District).filter(District.district_code == str(national_candidate["district_code"])).first()
        if district_n is None:
            raise RuntimeError("National candidate district not found in DB")

        district_stock_n = float(national_candidate["quantity"])
        state_stock_n = float(national_candidate["state_qty"])
        national_stock_n = float(national_candidate["national_qty"])
        resource_id_n = str(national_candidate["resource_id"])

        demand_national = district_stock_n + state_stock_n + min(50.0, max(1.0, national_stock_n * 0.000001))
        case_national = create_scenario_case(
            db,
            district=district_n,
            resource_id=resource_id_n,
            demand_qty=demand_national,
            state_qty=state_stock_n,
            national_qty=national_stock_n,
            name="EVIDENCE_NATIONAL_AUTOPULL",
        )
        report["cases"]["national_autopull"] = case_national

        demand_short = district_stock + state_stock + 1.0
        case_short = create_scenario_case(
            db,
            district=district,
            resource_id=resource_id,
            demand_qty=demand_short,
            state_qty=state_stock,
            national_qty=0.0,
            name="EVIDENCE_FULL_SHORTAGE",
        )
        report["cases"]["full_shortage"] = case_short

        # live run determinism
        out = create_request_batch(
            db,
            {"district_code": str(district.district_code), "state_code": str(district.state_code)},
            [
                {
                    "resource_id": "R1",
                    "time": 0,
                    "quantity": 1,
                    "priority": 1,
                    "urgency": 1,
                    "confidence": 1.0,
                    "source": "human",
                }
            ],
        )
        live_run_id = int(out["solver_run_id"])
        live_row = db.query(SolverRun).filter(SolverRun.id == live_run_id).first()
        fd_count = int(db.query(func.count(FinalDemand.id)).filter(FinalDemand.solver_run_id == live_run_id).scalar() or 0)
        alloc_count = int(db.query(func.count(Allocation.id)).filter(Allocation.solver_run_id == live_run_id).scalar() or 0)
        report["live_run"] = {
            "run_id": live_run_id,
            "status": str(live_row.status if live_row else "missing"),
            "final_demands": fd_count,
            "allocations": alloc_count,
        }

        # escalation non-blocking
        req = ResourceRequest(
            district_code=str(district.district_code),
            state_code=str(district.state_code),
            resource_id="R1",
            time=1,
            quantity=2.0,
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
        esc = escalate_request_to_national(db, int(req.id), actor_state=str(district.state_code), reason="evidence")
        rerun_id = trigger_live_solver_run(db)
        req_after = db.query(ResourceRequest).filter(ResourceRequest.id == int(req.id)).first()
        slot = slot_breakdown(db, int(rerun_id), str(district.district_code), "R1", 1)
        report["escalation_non_blocking"] = {
            "request_id": int(req.id),
            "status_after_escalate": str(esc.status),
            "rerun_id": int(rerun_id),
            "request_status_after_rerun": str(req_after.status if req_after else "missing"),
            "slot_metrics": slot,
        }

        # dashboard fallback evidence
        latest_live = db.query(SolverRun).filter(SolverRun.mode == "live", SolverRun.status == "completed").order_by(SolverRun.id.desc()).first()
        latest_any = db.query(SolverRun).filter(SolverRun.status == "completed").order_by(SolverRun.id.desc()).first()

        flipped_live_ids = [int(r.id) for r in db.query(SolverRun).filter(SolverRun.mode == "live", SolverRun.status == "completed").all()]
        if flipped_live_ids:
            for row in db.query(SolverRun).filter(SolverRun.id.in_(flipped_live_ids)).all():
                row.status = "failed"
            db.commit()

        fallback = get_latest_completed_run(db)

        for rid in flipped_live_ids:
            row = db.query(SolverRun).filter(SolverRun.id == rid).first()
            if row is not None:
                row.status = "completed"
        if flipped_live_ids:
            db.commit()

        report["dashboard_fallback"] = {
            "latest_completed_live_before": None if latest_live is None else {"id": int(latest_live.id), "mode": str(latest_live.mode)},
            "latest_completed_any_before": None if latest_any is None else {"id": int(latest_any.id), "mode": str(latest_any.mode)},
            "selected_when_no_live_completed": None if fallback is None else {"id": int(fallback.id), "mode": str(fallback.mode)},
        }

        report["baseline"] = {
            "latest_solver_runs": [
                {
                    "id": int(r.id),
                    "mode": str(r.mode),
                    "status": str(r.status),
                    "started_at": None if r.started_at is None else str(r.started_at),
                }
                for r in db.query(SolverRun).order_by(SolverRun.id.desc()).limit(10).all()
            ]
        }

    finally:
        db.close()

    out_path = Path("stability_evidence.json")
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
