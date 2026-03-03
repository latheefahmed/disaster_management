import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session
import math

from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.allocation import Allocation


DEMAND_UNIT_MULTIPLIER = 1


def _normalize_code(value) -> str:
    raw = str(value).strip()
    if raw.endswith('.0'):
        raw = raw[:-2]
    return raw


def normalize_final_demand_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "district_code", "resource_id", "time", "demand", "demand_mode", "source_mix"
        ])

    work = df.copy()
    required = {"district_code", "resource_id", "time", "demand"}
    if not required.issubset(work.columns):
        return pd.DataFrame(columns=[
            "district_code", "resource_id", "time", "demand", "demand_mode", "source_mix"
        ])

    if "demand_mode" not in work.columns:
        work["demand_mode"] = "baseline_plus_human"
    if "source_mix" not in work.columns:
        work["source_mix"] = "merged"

    work["district_code"] = work["district_code"].map(_normalize_code)
    work["resource_id"] = work["resource_id"].astype(str)
    work["time"] = work["time"].astype(int)
    work["demand"] = work["demand"].astype(float) * DEMAND_UNIT_MULTIPLIER
    work["demand"] = work["demand"].map(lambda v: float(math.ceil(v)) if float(v) > 0.0 else 0.0)
    work["demand_mode"] = work["demand_mode"].astype(str)
    work["source_mix"] = work["source_mix"].astype(str)

    grouped = work.groupby(
        ["district_code", "resource_id", "time", "demand_mode", "source_mix"],
        as_index=False,
    )["demand"].sum()

    return grouped[grouped["demand"] > 0].copy()


def persist_final_demands(db: Session, solver_run_id: int, final_df: pd.DataFrame):
    rows = normalize_final_demand_frame(final_df)

    db.query(FinalDemand).filter(FinalDemand.solver_run_id == int(solver_run_id)).delete(synchronize_session=False)

    if rows.empty:
        return

    district_to_state = {
        _normalize_code(row.district_code): _normalize_code(row.state_code)
        for row in db.query(District).all()
    }

    payload = []
    for row in rows.itertuples(index=False):
        district_code = _normalize_code(row.district_code)
        payload.append({
            "solver_run_id": int(solver_run_id),
            "district_code": district_code,
            "state_code": district_to_state.get(district_code),
            "resource_id": str(row.resource_id),
            "time": int(row.time),
            "demand_quantity": float(row.demand),
            "demand_mode": str(row.demand_mode),
            "source_mix": str(row.source_mix),
        })

    db.bulk_insert_mappings(FinalDemand, payload)


def get_final_demand_slot_map(
    db: Session,
    solver_run_id: int,
    district_code: str | None = None,
    state_code: str | None = None,
):
    query = db.query(
        FinalDemand.district_code,
        FinalDemand.resource_id,
        FinalDemand.time,
        func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0).label("demand_total"),
    ).filter(FinalDemand.solver_run_id == int(solver_run_id))

    if district_code is not None:
        query = query.filter(FinalDemand.district_code == _normalize_code(district_code))

    if state_code is not None:
        query = query.filter(FinalDemand.state_code == _normalize_code(state_code))

    rows = query.group_by(
        FinalDemand.district_code,
        FinalDemand.resource_id,
        FinalDemand.time,
    ).all()

    return {
        (_normalize_code(row.district_code), str(row.resource_id), int(row.time)): float(row.demand_total or 0.0)
        for row in rows
    }


def reconcile_final_demands_with_allocations(db: Session, solver_run_id: int):
    slot_rows = db.query(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("demand_total"),
    ).filter(
        Allocation.solver_run_id == int(solver_run_id),
    ).group_by(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    slot_map = {
        (_normalize_code(r.district_code), str(r.resource_id), int(r.time)): (
            float(math.ceil(float(r.demand_total or 0.0))) if float(r.demand_total or 0.0) > 0.0 else 0.0
        )
        for r in slot_rows
    }

    if not slot_map:
        return

    district_to_state = {
        _normalize_code(row.district_code): _normalize_code(row.state_code)
        for row in db.query(District).all()
    }

    existing_rows = db.query(FinalDemand).filter(FinalDemand.solver_run_id == int(solver_run_id)).all()
    existing_map = {
        (_normalize_code(r.district_code), str(r.resource_id), int(r.time)): r
        for r in existing_rows
    }

    for key, total in slot_map.items():
        row = existing_map.get(key)
        if row is not None:
            row.demand_quantity = float(total)
            continue

        district_code, resource_id, time = key
        db.add(FinalDemand(
            solver_run_id=int(solver_run_id),
            district_code=district_code,
            state_code=district_to_state.get(district_code),
            resource_id=resource_id,
            time=int(time),
            demand_quantity=float(total),
            demand_mode="baseline_plus_human",
            source_mix="solver_reconciled",
        ))

    for key, row in existing_map.items():
        if key not in slot_map:
            db.delete(row)


def integerize_final_demands(db: Session, solver_run_id: int | None = None) -> int:
    query = db.query(FinalDemand)
    if solver_run_id is not None:
        query = query.filter(FinalDemand.solver_run_id == int(solver_run_id))

    rows = query.all()
    changed = 0
    for row in rows:
        current = float(row.demand_quantity or 0.0)
        target = float(math.ceil(current)) if current > 0.0 else 0.0
        if abs(current - target) > 1e-9:
            row.demand_quantity = target
            changed += 1
    return changed
