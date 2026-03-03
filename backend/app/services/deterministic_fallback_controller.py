from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.allocation import Allocation
from app.models.final_demand import FinalDemand
from app.models.solver_run import SolverRun


def _latest_completed_run_ids(db: Session, limit: int = 30) -> list[int]:
    rows = db.query(SolverRun).filter(
        SolverRun.mode == "live",
        SolverRun.status == "completed",
    ).order_by(SolverRun.id.desc()).limit(max(1, int(limit))).all()
    return [int(r.id) for r in rows]


def get_params(db: Session, solver_run_id: int | None = None) -> dict:
    run_ids = _latest_completed_run_ids(db)
    if not run_ids:
        return {"alpha": 0.5, "beta": 0.5, "gamma": 1.0, "p_mult": 1.0, "u_mult": 1.0, "source": "fallback"}

    total_demand = db.query(func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0)).filter(
        FinalDemand.solver_run_id.in_(run_ids),
    ).scalar() or 0.0

    total_unmet = db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
        Allocation.solver_run_id.in_(run_ids),
        Allocation.is_unmet == True,
    ).scalar() or 0.0

    unmet_ratio = 0.0 if float(total_demand) <= 1e-9 else float(total_unmet) / float(total_demand)
    alpha = max(0.2, min(0.8, 0.6 - 0.2 * unmet_ratio))
    beta = 1.0 - alpha
    gamma = max(1.0, min(2.0, 1.0 + 0.6 * unmet_ratio))
    p_mult = max(0.8, min(1.3, 1.0 + 0.2 * unmet_ratio))
    u_mult = max(0.8, min(1.3, 1.0 + 0.15 * unmet_ratio))

    return {
        "alpha": float(alpha),
        "beta": float(beta),
        "gamma": float(gamma),
        "p_mult": float(p_mult),
        "u_mult": float(u_mult),
        "source": "fallback",
        "unmet_ratio": float(unmet_ratio),
    }
