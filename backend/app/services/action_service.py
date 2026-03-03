from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.claim import Claim
from app.models.consumption import Consumption
from app.models.return_ import Return
from app.models.pool_transaction import PoolTransaction
from app.models.stock_refill_transaction import StockRefillTransaction
from app.models.allocation import Allocation
from app.models.solver_run import SolverRun
from app.models.district import District
from app.services.audit_service import log_event, log_entity_event
from app.services.resource_policy import is_resource_returnable, is_resource_consumable
from app.services.resource_dictionary_service import resolve_resource_id
from app.services.canonical_resources import max_quantity_for, requires_integer_quantity
from app.config import ENABLE_MUTUAL_AID
from app.services.mutual_aid_service import (
    resolve_primary_origin_state_for_slot,
    record_return_transfer,
)


def _latest_live_run_id(db: Session) -> int | None:
    row = db.query(SolverRun)\
        .filter(
            SolverRun.status == "completed",
            SolverRun.mode == "live",
        )\
        .order_by(SolverRun.id.desc())\
        .first()
    return row.id if row else None


def _resolve_action_run_id(db: Session, solver_run_id: int | None) -> int:
    if solver_run_id is None:
        run_id = _latest_live_run_id(db)
        if not run_id:
            raise ValueError("No live solver run available")
        return int(run_id)

    run = db.query(SolverRun).filter(SolverRun.id == int(solver_run_id)).first()
    if not run:
        raise ValueError(f"Solver run '{solver_run_id}' was not found")
    if str(run.status or "").lower() != "completed":
        raise ValueError(f"Solver run '{solver_run_id}' is not completed")
    return int(run.id)


def _allocated_quantity_for_slot(
    db: Session,
    solver_run_id: int,
    district_code: str,
    resource_id: str,
    time: int,
) -> float:
    value = db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0))\
        .filter(
            Allocation.solver_run_id == solver_run_id,
            Allocation.district_code == district_code,
            Allocation.resource_id == resource_id,
            Allocation.time == time,
            Allocation.is_unmet == False,
        )\
        .scalar()

    return float(value or 0.0)


def _claimed_quantity(db: Session, solver_run_id: int, district_code: str, resource_id: str, time: int) -> float:
    value = db.query(func.coalesce(func.sum(Claim.quantity), 0.0))\
        .filter(
            Claim.solver_run_id == solver_run_id,
            Claim.district_code == district_code,
            Claim.resource_id == resource_id,
            Claim.time == time,
        )\
        .scalar()
    return float(value or 0.0)


def _consumed_quantity(db: Session, solver_run_id: int, district_code: str, resource_id: str, time: int) -> float:
    value = db.query(func.coalesce(func.sum(Consumption.quantity), 0.0))\
        .filter(
            Consumption.solver_run_id == solver_run_id,
            Consumption.district_code == district_code,
            Consumption.resource_id == resource_id,
            Consumption.time == time,
        )\
        .scalar()
    return float(value or 0.0)


def _returned_quantity(db: Session, solver_run_id: int, district_code: str, resource_id: str, time: int) -> float:
    value = db.query(func.coalesce(func.sum(Return.quantity), 0.0))\
        .filter(
            Return.solver_run_id == solver_run_id,
            Return.district_code == district_code,
            Return.resource_id == resource_id,
            Return.time == time,
        )\
        .scalar()
    return float(value or 0.0)


def _slot_status(allocated: float, claimed: float, consumed: float, returned: float) -> str:
    if allocated <= 1e-9:
        return "empty"
    if claimed <= 1e-9:
        return "allocated"

    remaining = max(0.0, claimed - consumed - returned)
    if returned > 1e-9 and remaining <= 1e-9:
        return "RETURNED"
    if consumed > 1e-9 and remaining <= 1e-9:
        return "consumed"
    if remaining <= 1e-9:
        return "claimed"
    if consumed > 0:
        return "partially_consumed"
    if returned > 0:
        return "partially_returned"
    return "claimed"


def _assert_action_allowed(action: str, status: str):
    action_name = str(action).upper()
    current = str(status or "EMPTY").upper()

    allowed_by_action = {
        "CLAIM": {"ALLOCATED", "CLAIMED", "PARTIALLY_CONSUMED", "PARTIALLY_RETURNED"},
        "CONSUME": {"CLAIMED", "PARTIALLY_CONSUMED", "PARTIALLY_RETURNED"},
        "RETURN": {"CLAIMED", "PARTIALLY_CONSUMED", "PARTIALLY_RETURNED"},
    }

    allowed = allowed_by_action.get(action_name, set())
    if current not in allowed:
        raise ValueError(f"Cannot {action_name.lower()} in allocation status '{current}'")


def _normalize_action_quantity(resource_id: str, quantity_value) -> float:
    try:
        quantity = float(quantity_value)
    except (TypeError, ValueError):
        raise ValueError("quantity must be a number")

    if quantity <= 0:
        raise ValueError("quantity must be greater than 0")

    if requires_integer_quantity(resource_id) and not float(quantity).is_integer():
        raise ValueError(f"quantity for resource '{resource_id}' must be a whole number")

    max_qty = float(max_quantity_for(resource_id))
    if quantity > max_qty:
        raise ValueError(f"quantity exceeds max allowed for resource '{resource_id}' ({max_qty:.0f})")

    return float(quantity)


def _effective_slot_resource_id(
    db: Session,
    solver_run_id: int,
    district_code: str,
    input_resource_id: str,
    normalized_resource_id: str,
    time: int,
) -> str:
    normalized = str(normalized_resource_id)
    raw = str(input_resource_id)

    if raw == normalized:
        return normalized

    normalized_alloc = _allocated_quantity_for_slot(db, solver_run_id, district_code, normalized, time)
    if normalized_alloc > 1e-9:
        return normalized

    raw_alloc = _allocated_quantity_for_slot(db, solver_run_id, district_code, raw, time)
    if raw_alloc > 1e-9:
        return raw

    return normalized


def _sync_allocation_slot(
    db: Session,
    solver_run_id: int,
    district_code: str,
    resource_id: str,
    time: int,
):
    rows = db.query(Allocation)\
        .filter(
            Allocation.solver_run_id == solver_run_id,
            Allocation.district_code == district_code,
            Allocation.resource_id == resource_id,
            Allocation.time == time,
            Allocation.is_unmet == False,
        )\
        .all()

    if not rows:
        return {
            "allocated_quantity": 0.0,
            "claimed_quantity": 0.0,
            "consumed_quantity": 0.0,
            "returned_quantity": 0.0,
            "remaining_quantity": 0.0,
            "status": "EMPTY",
        }

    allocated = float(sum(float(r.allocated_quantity or 0.0) for r in rows))
    claimed = _claimed_quantity(db, solver_run_id, district_code, resource_id, time)
    consumed = _consumed_quantity(db, solver_run_id, district_code, resource_id, time)
    returned = _returned_quantity(db, solver_run_id, district_code, resource_id, time)
    remaining = max(0.0, claimed - consumed - returned)
    status = _slot_status(allocated, claimed, consumed, returned)

    for row in rows:
        row.claimed_quantity = claimed
        row.consumed_quantity = consumed
        row.returned_quantity = returned
        row.status = status

    return {
        "allocated_quantity": allocated,
        "claimed_quantity": claimed,
        "consumed_quantity": consumed,
        "returned_quantity": returned,
        "remaining_quantity": remaining,
        "status": status,
    }


def _lock_slot_allocation_rows(
    db: Session,
    solver_run_id: int,
    district_code: str,
    resource_id: str,
    time: int,
):
    query = db.query(Allocation)\
        .filter(
            Allocation.solver_run_id == solver_run_id,
            Allocation.district_code == district_code,
            Allocation.resource_id == resource_id,
            Allocation.time == time,
            Allocation.is_unmet == False,
        )
    try:
        return query.with_for_update().all()
    except Exception:
        return query.all()


def create_claim(db: Session, district_code: str, resource_id: str,
                 time: int, quantity: float, claimed_by: str = "district_manager", solver_run_id: int | None = None):

    normalized_resource_id = resolve_resource_id(db, resource_id, strict=False)
    normalized_quantity = _normalize_action_quantity(normalized_resource_id, quantity)

    run_id = _resolve_action_run_id(db, solver_run_id)

    slot_resource_id = _effective_slot_resource_id(
        db,
        int(run_id),
        str(district_code),
        str(resource_id),
        str(normalized_resource_id),
        int(time),
    )

    slot_rows = _lock_slot_allocation_rows(db, run_id, district_code, slot_resource_id, time)
    allocated = float(sum(float(r.allocated_quantity or 0.0) for r in slot_rows))
    already_claimed = _claimed_quantity(db, run_id, district_code, slot_resource_id, time)
    already_consumed = _consumed_quantity(db, run_id, district_code, slot_resource_id, time)
    already_returned = _returned_quantity(db, run_id, district_code, slot_resource_id, time)
    status_before = _slot_status(allocated, already_claimed, already_consumed, already_returned)

    _assert_action_allowed("CLAIM", status_before)

    if already_claimed + normalized_quantity > allocated + 1e-9:
        raise ValueError("Claim quantity exceeds allocated quantity")

    with db.begin_nested():
        row = Claim(
            solver_run_id=run_id,
            district_code=district_code,
            resource_id=slot_resource_id,
            time=time,
            quantity=normalized_quantity,
            claimed_by=claimed_by,
        )

        db.add(row)
        db.flush()
        snapshot = _sync_allocation_slot(db, run_id, district_code, slot_resource_id, time)

    log_event(
        actor_role="district",
        actor_id=district_code,
        event_type="CLAIM",
        payload={
            "resource_id": slot_resource_id,
            "time": time,
            "quantity": normalized_quantity,
            "solver_run_id": run_id,
        },
        db=db,
    )
    log_entity_event(
        db,
        user_id=district_code,
        action="CLAIM",
        entity_type="allocation_slot",
        entity_id=f"{run_id}:{district_code}:{slot_resource_id}:{time}",
        before=None,
        after=snapshot,
        actor_role="district",
        actor_id=district_code,
    )

    db.commit()
    db.refresh(row)

    return row, snapshot


def create_consumption(db: Session, district_code: str, resource_id: str,
                       time: int, quantity: float, solver_run_id: int | None = None):

    normalized_resource_id = resolve_resource_id(db, resource_id, strict=False)
    normalized_quantity = _normalize_action_quantity(normalized_resource_id, quantity)

    if not is_resource_consumable(normalized_resource_id):
        raise ValueError(f"Resource '{normalized_resource_id}' is reusable and cannot be consumed. Return it instead")

    run_id = _resolve_action_run_id(db, solver_run_id)

    slot_resource_id = _effective_slot_resource_id(
        db,
        int(run_id),
        str(district_code),
        str(resource_id),
        str(normalized_resource_id),
        int(time),
    )

    _lock_slot_allocation_rows(db, run_id, district_code, slot_resource_id, time)
    claimed = _claimed_quantity(db, run_id, district_code, slot_resource_id, time)
    consumed = _consumed_quantity(db, run_id, district_code, slot_resource_id, time)
    returned = _returned_quantity(db, run_id, district_code, slot_resource_id, time)
    allocated = _allocated_quantity_for_slot(db, run_id, district_code, slot_resource_id, time)
    status_before = _slot_status(allocated, claimed, consumed, returned)
    _assert_action_allowed("CONSUME", status_before)

    remaining = claimed - consumed - returned

    if normalized_quantity > remaining + 1e-9:
        raise ValueError("Consume quantity exceeds claimed remaining quantity")

    with db.begin_nested():
        row = Consumption(
            solver_run_id=run_id,
            district_code=district_code,
            resource_id=slot_resource_id,
            time=time,
            quantity=normalized_quantity
        )

        db.add(row)
        db.flush()
        snapshot = _sync_allocation_slot(db, run_id, district_code, slot_resource_id, time)

    log_event(
        actor_role="district",
        actor_id=district_code,
        event_type="CONSUME",
        payload={
            "resource_id": slot_resource_id,
            "time": time,
            "quantity": normalized_quantity,
            "solver_run_id": run_id,
        },
        db=db,
    )

    log_entity_event(
        db,
        user_id=district_code,
        action="CONSUME",
        entity_type="allocation_slot",
        entity_id=f"{run_id}:{district_code}:{slot_resource_id}:{time}",
        before=None,
        after=snapshot,
        actor_role="district",
        actor_id=district_code,
    )

    db.commit()
    db.refresh(row)

    return row, snapshot


def create_return(db: Session, district_code: str, resource_id: str,
                  state_code: str, time: int, quantity: float, reason: str, solver_run_id: int | None = None,
                  allocation_source_scope: str | None = None, allocation_source_code: str | None = None):

    normalized_resource_id = resolve_resource_id(db, resource_id, strict=False)
    normalized_quantity = _normalize_action_quantity(normalized_resource_id, quantity)

    if not is_resource_returnable(normalized_resource_id):
        raise ValueError(f"Resource '{normalized_resource_id}' is non-returnable and cannot be added to pool")

    run_id = _resolve_action_run_id(db, solver_run_id)

    slot_resource_id = _effective_slot_resource_id(
        db,
        int(run_id),
        str(district_code),
        str(resource_id),
        str(normalized_resource_id),
        int(time),
    )

    _lock_slot_allocation_rows(db, run_id, district_code, slot_resource_id, time)
    claimed = _claimed_quantity(db, run_id, district_code, slot_resource_id, time)
    consumed = _consumed_quantity(db, run_id, district_code, slot_resource_id, time)
    already_returned = _returned_quantity(db, run_id, district_code, slot_resource_id, time)
    allocated = _allocated_quantity_for_slot(db, run_id, district_code, slot_resource_id, time)
    status_before = _slot_status(allocated, claimed, consumed, already_returned)
    _assert_action_allowed("RETURN", status_before)

    remaining = claimed - consumed - already_returned

    if normalized_quantity > remaining + 1e-9:
        raise ValueError("Return quantity exceeds claimed remaining quantity")

    source_scope = str(allocation_source_scope or "").strip().lower()
    source_code = str(allocation_source_code or "").strip()
    if source_scope not in {"district", "state", "neighbor_state", "national"}:
        source_scope = ""
    if source_code in {"", "—", "None", "none", "null"}:
        source_code = ""

    with db.begin_nested():
        row = Return(
            solver_run_id=run_id,
            district_code=district_code,
            resource_id=slot_resource_id,
            time=time,
            quantity=normalized_quantity,
            reason=reason,
        )

        db.add(row)

        if source_scope == "district":
            db.add(StockRefillTransaction(
                scope="district",
                district_code=str(district_code),
                state_code=str(state_code),
                resource_id=str(slot_resource_id),
                quantity_delta=float(normalized_quantity),
                reason=f"district_return:{reason}",
                actor_role="district",
                actor_id=str(district_code),
                source="district_return_credit",
                solver_run_id=int(run_id),
            ))
        else:
            if source_scope in {"state", "neighbor_state"} and source_code:
                target_state_for_return = str(source_code)
            elif source_scope == "national":
                target_state_for_return = "NATIONAL"
            else:
                target_state_for_return = resolve_primary_origin_state_for_slot(
                    db=db,
                    solver_run_id=int(run_id),
                    district_code=str(district_code),
                    state_code=str(state_code),
                    resource_id=str(slot_resource_id),
                    time=int(time),
                )

            pool_row = PoolTransaction(
                state_code=target_state_for_return,
                district_code=district_code,
                resource_id=slot_resource_id,
                time=time,
                quantity_delta=float(normalized_quantity),
                reason=(
                    f"district_return_to_origin:{reason}" if target_state_for_return != str(state_code)
                    else f"district_return:{reason}"
                ),
                actor_role="district",
                actor_id=district_code,
            )
            db.add(pool_row)

            if target_state_for_return != str(state_code):
                record_return_transfer(
                    db=db,
                    solver_run_id=int(run_id),
                    from_state=str(state_code),
                    to_state=str(target_state_for_return),
                    resource_id=str(slot_resource_id),
                    time=int(time),
                    quantity=float(normalized_quantity),
                )
        db.flush()

        snapshot = _sync_allocation_slot(db, run_id, district_code, slot_resource_id, time)

    log_event(
        actor_role="district",
        actor_id=district_code,
        event_type="RETURN",
        payload={
            "resource_id": slot_resource_id,
            "time": time,
            "quantity": normalized_quantity,
            "reason": reason,
            "solver_run_id": run_id,
        },
        db=db,
    )

    log_entity_event(
        db,
        user_id=district_code,
        action="RETURN",
        entity_type="allocation_slot",
        entity_id=f"{run_id}:{district_code}:{slot_resource_id}:{time}",
        before=None,
        after=snapshot,
        actor_role="district",
        actor_id=district_code,
    )

    db.commit()
    db.refresh(row)

    return row, snapshot


def list_claims_for_district(db: Session, district_code: str, limit: int = 100, offset: int = 0):
    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))
    return db.query(Claim)\
        .join(SolverRun, SolverRun.id == Claim.solver_run_id)\
        .filter(
            Claim.district_code == district_code,
            SolverRun.status == "completed",
        )\
        .order_by(Claim.created_at.desc(), Claim.id.desc())\
        .offset(safe_offset)\
        .limit(safe_limit)\
        .all()


def list_consumption_for_district(db: Session, district_code: str, limit: int = 100, offset: int = 0):
    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))
    return db.query(Consumption)\
        .join(SolverRun, SolverRun.id == Consumption.solver_run_id)\
        .filter(
            Consumption.district_code == district_code,
            SolverRun.status == "completed",
        )\
        .order_by(Consumption.created_at.desc(), Consumption.id.desc())\
        .offset(safe_offset)\
        .limit(safe_limit)\
        .all()


def list_returns_for_district(db: Session, district_code: str, limit: int = 100, offset: int = 0):
    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))
    return db.query(Return)\
        .join(SolverRun, SolverRun.id == Return.solver_run_id)\
        .filter(
            Return.district_code == district_code,
            SolverRun.status == "completed",
        )\
        .order_by(Return.created_at.desc(), Return.id.desc())\
        .offset(safe_offset)\
        .limit(safe_limit)\
        .all()


def _pool_balance_query(db: Session, state_code: str | None = None):
    query = db.query(
        PoolTransaction.resource_id,
        PoolTransaction.time,
        func.coalesce(func.sum(PoolTransaction.quantity_delta), 0.0).label("quantity"),
    )
    if state_code is not None:
        query = query.filter(PoolTransaction.state_code == state_code)
    return query.group_by(PoolTransaction.resource_id, PoolTransaction.time)


def get_state_pool_balance(db: Session, state_code: str):
    rows = _pool_balance_query(db, state_code).all()
    return [
        {
            "resource_id": row.resource_id,
            "time": int(row.time),
            "quantity": max(0.0, float(row.quantity or 0.0)),
        }
        for row in rows
        if float(row.quantity or 0.0) > 1e-9 and is_resource_returnable(str(row.resource_id))
    ]


def list_state_pool_transactions(db: Session, state_code: str, limit: int = 200):
    rows = db.query(PoolTransaction)\
        .filter(PoolTransaction.state_code == state_code)\
        .order_by(PoolTransaction.id.desc())\
        .limit(int(limit))\
        .all()

    payload = []
    for row in rows:
        payload.append({
            "id": int(row.id),
            "state_code": row.state_code,
            "district_code": row.district_code,
            "resource_id": row.resource_id,
            "time": int(row.time),
            "quantity_delta": float(row.quantity_delta or 0.0),
            "reason": row.reason,
            "actor_role": row.actor_role,
            "actor_id": row.actor_id,
            "created_at": row.created_at,
        })
    return payload


def list_global_pool_transactions(db: Session, limit: int = 300):
    rows = db.query(PoolTransaction)\
        .order_by(PoolTransaction.id.desc())\
        .limit(int(limit))\
        .all()

    payload = []
    for row in rows:
        if not is_resource_returnable(str(row.resource_id)):
            continue
        payload.append({
            "id": int(row.id),
            "state_code": row.state_code,
            "district_code": row.district_code,
            "resource_id": row.resource_id,
            "time": int(row.time),
            "quantity_delta": float(row.quantity_delta or 0.0),
            "reason": row.reason,
            "actor_role": row.actor_role,
            "actor_id": row.actor_id,
            "created_at": row.created_at,
        })
    return payload


def get_global_pool_balance(db: Session):
    rows = _pool_balance_query(db, None).all()
    return [
        {
            "resource_id": row.resource_id,
            "time": int(row.time),
            "quantity": max(0.0, float(row.quantity or 0.0)),
        }
        for row in rows
        if float(row.quantity or 0.0) > 1e-9 and is_resource_returnable(str(row.resource_id))
    ]


def allocate_from_state_pool(
    db: Session,
    actor_state: str,
    resource_id: str,
    time: int,
    quantity: float,
    target_district: str | None = None,
    note: str | None = None,
):
    normalized_resource_id = resolve_resource_id(db, resource_id, strict=True)
    normalized_quantity = _normalize_action_quantity(normalized_resource_id, quantity)

    if not is_resource_returnable(normalized_resource_id):
        raise ValueError(f"Resource '{normalized_resource_id}' is non-returnable and cannot be allocated from pool")

    available = 0.0
    for row in get_state_pool_balance(db, actor_state):
        if str(row["resource_id"]) == str(normalized_resource_id) and int(row["time"]) == int(time):
            available = float(row["quantity"])
            break

    if normalized_quantity > available + 1e-9:
        raise ValueError("Requested quantity exceeds state pool availability")

    tx = PoolTransaction(
        state_code=actor_state,
        district_code=target_district,
        resource_id=normalized_resource_id,
        time=int(time),
        quantity_delta=-float(normalized_quantity),
        reason=f"state_allocate:{note or ''}".strip(":"),
        actor_role="state",
        actor_id=actor_state,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    log_event(
        actor_role="state",
        actor_id=str(actor_state),
        event_type="STATE_POOL_ALLOCATE",
        payload={
            "resource_id": normalized_resource_id,
            "time": int(time),
            "quantity": float(normalized_quantity),
            "target_district": target_district,
            "note": note or "",
        },
    )

    return tx


def allocate_from_pool_as_national(
    db: Session,
    state_code: str,
    resource_id: str,
    time: int,
    quantity: float,
    target_district: str | None = None,
    note: str | None = None,
):
    normalized_resource_id = resolve_resource_id(db, resource_id, strict=True)
    normalized_quantity = _normalize_action_quantity(normalized_resource_id, quantity)

    if not is_resource_returnable(normalized_resource_id):
        raise ValueError(f"Resource '{normalized_resource_id}' is non-returnable and cannot be allocated from pool")

    available = 0.0
    for row in get_state_pool_balance(db, state_code):
        if str(row["resource_id"]) == str(normalized_resource_id) and int(row["time"]) == int(time):
            available = float(row["quantity"])
            break

    if normalized_quantity > available + 1e-9:
        raise ValueError("Requested quantity exceeds available pool quantity")

    tx = PoolTransaction(
        state_code=state_code,
        district_code=target_district,
        resource_id=normalized_resource_id,
        time=int(time),
        quantity_delta=-float(normalized_quantity),
        reason=f"national_allocate:{note or ''}".strip(":"),
        actor_role="national",
        actor_id="NATIONAL",
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    log_event(
        actor_role="national",
        actor_id="NATIONAL",
        event_type="NATIONAL_POOL_ALLOCATE",
        payload={
            "state_code": state_code,
            "resource_id": normalized_resource_id,
            "time": int(time),
            "quantity": float(normalized_quantity),
            "target_district": target_district,
            "note": note or "",
        },
    )

    return tx


def resolve_state_for_district(db: Session, district_code: str) -> str | None:
    row = db.query(District).filter(District.district_code == district_code).first()
    if not row:
        return None
    return str(row.state_code)
