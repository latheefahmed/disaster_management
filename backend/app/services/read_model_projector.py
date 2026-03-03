from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.allocation import Allocation
from app.models.solver_run import SolverRun
from app.services.cache_service import set_cached


def _latest_completed_run_id(db: Session) -> int:
    row = db.query(SolverRun.id).filter(SolverRun.status == "completed").order_by(SolverRun.id.desc()).first()
    return int(row[0]) if row else 0


def project_district_snapshot(db: Session, district_code: str) -> dict[str, Any]:
    latest_run = _latest_completed_run_id(db)
    allocated = db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
        Allocation.solver_run_id == latest_run,
        Allocation.district_code == str(district_code),
        Allocation.is_unmet == False,
    ).scalar()
    unmet = db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
        Allocation.solver_run_id == latest_run,
        Allocation.district_code == str(district_code),
        Allocation.is_unmet == True,
    ).scalar()
    payload = {
        "solver_run_id": int(latest_run),
        "district_code": str(district_code),
        "allocated": float(allocated or 0.0),
        "unmet": float(unmet or 0.0),
    }
    set_cached(f"readmodel:district:{district_code}", payload, ttl_seconds=30.0)
    return payload


def project_state_snapshot(db: Session, state_code: str) -> dict[str, Any]:
    latest_run = _latest_completed_run_id(db)
    allocated = db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
        Allocation.solver_run_id == latest_run,
        Allocation.state_code == str(state_code),
        Allocation.is_unmet == False,
    ).scalar()
    unmet = db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
        Allocation.solver_run_id == latest_run,
        Allocation.state_code == str(state_code),
        Allocation.is_unmet == True,
    ).scalar()
    payload = {
        "solver_run_id": int(latest_run),
        "state_code": str(state_code),
        "allocated": float(allocated or 0.0),
        "unmet": float(unmet or 0.0),
    }
    set_cached(f"readmodel:state:{state_code}", payload, ttl_seconds=30.0)
    return payload


def project_national_snapshot(db: Session) -> dict[str, Any]:
    latest_run = _latest_completed_run_id(db)
    allocated = db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
        Allocation.solver_run_id == latest_run,
        Allocation.is_unmet == False,
    ).scalar()
    unmet = db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
        Allocation.solver_run_id == latest_run,
        Allocation.is_unmet == True,
    ).scalar()
    payload = {
        "solver_run_id": int(latest_run),
        "allocated": float(allocated or 0.0),
        "unmet": float(unmet or 0.0),
    }
    set_cached("readmodel:national", payload, ttl_seconds=30.0)
    return payload
