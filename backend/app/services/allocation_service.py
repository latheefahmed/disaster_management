from sqlalchemy.orm import Session
from datetime import datetime
from app.models.allocation import Allocation
from app.models.solver_run import SolverRun


# ============================================================
# HARD RESET — Clear All Allocations
# ============================================================

def clear_allocations(db: Session):
    db.query(Allocation).delete()
    db.commit()


# ============================================================
# CLEAR ONE SOLVER RUN
# ============================================================

def clear_allocations_for_run(
    db: Session,
    solver_run_id: int,
    auto_commit: bool = True,
):
    db.query(Allocation)\
        .filter(Allocation.solver_run_id == solver_run_id)\
        .delete()
    if auto_commit:
        db.commit()


# ============================================================
# SINGLE INSERT (kept for compatibility)
# ============================================================

def create_allocation(
    db: Session,
    solver_run_id: int,
    request_id: int,
    resource_id: str,
    district_code: str,
    state_code: str,
    time: int,
    quantity: float,
    is_unmet: bool
):

    row = Allocation(
        solver_run_id=solver_run_id,
        request_id=request_id,
        resource_id=resource_id,
        district_code=district_code,
        state_code=state_code,
        time=time,
        allocated_quantity=quantity,
        is_unmet=is_unmet
    )

    db.add(row)
    db.commit()


# ============================================================
# BULK INSERT (NEW)
# ============================================================

def create_allocations_bulk(
    db: Session,
    rows: list[dict],
    auto_commit: bool = True,
):
    if not rows:
        if auto_commit:
            db.commit()
        return
    objects = [Allocation(**r) for r in rows]
    db.bulk_save_objects(objects)
    if auto_commit:
        db.commit()


def confirm_allocation_receipt(
    db: Session,
    allocation_id: int,
    district_code: str,
):
    row = db.query(Allocation).filter(
        Allocation.id == int(allocation_id),
        Allocation.district_code == str(district_code),
        Allocation.is_unmet == False,
    ).first()
    if row is None:
        raise ValueError("Allocation not found")

    row.receipt_confirmed = True
    row.receipt_time = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def get_latest_completed_run(db: Session):
    latest_live = db.query(SolverRun)\
        .filter(SolverRun.mode == "live", SolverRun.status == "completed")\
        .order_by(SolverRun.id.desc())\
        .first()
    if latest_live is not None:
        return latest_live

    latest_any = db.query(SolverRun)\
        .filter(SolverRun.status == "completed")\
        .order_by(SolverRun.id.desc())\
        .first()
    return latest_any
