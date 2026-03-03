from __future__ import annotations

from math import radians, sin, cos, sqrt, atan2
from pathlib import Path

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.allocation import Allocation
from app.models.mutual_aid_offer import MutualAidOffer
from app.models.mutual_aid_request import MutualAidRequest
from app.models.state import State
from app.models.state_transfer import StateTransfer
from app.config import AVG_SPEED_KMPH


REQUEST_OPEN_STATUSES = {"open", "partially_filled"}
REQUEST_FINAL_STATUSES = {"satisfied", "cancelled"}
OFFER_OPEN_STATUSES = {"pending"}
OFFER_ACCEPTED_STATUSES = {"accepted"}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = radians(float(lat2) - float(lat1))
    d_lon = radians(float(lon2) - float(lon1))
    a = sin(d_lat / 2) ** 2 + cos(radians(float(lat1))) * cos(radians(float(lat2))) * sin(d_lon / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _implied_delay_hours(db: Session, origin_state: str, destination_state: str) -> float:
    if str(origin_state) == str(destination_state):
        return 0.0
    if float(AVG_SPEED_KMPH) <= 0.0:
        return 0.0
    coords = _state_coords(db)
    origin = coords.get(str(origin_state))
    destination = coords.get(str(destination_state))
    if origin is None or destination is None:
        return 0.0
    return max(0.0, haversine_km(origin[0], origin[1], destination[0], destination[1]) / float(AVG_SPEED_KMPH))


def _state_coords(db: Session) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for row in db.query(State).all():
        if row.latitude is None or row.longitude is None:
            continue
        out[str(row.state_code)] = (float(row.latitude), float(row.longitude))
    return out


def get_candidate_states(db: Session, requesting_state: str, limit: int = 10) -> list[dict]:
    coords = _state_coords(db)
    src = coords.get(str(requesting_state))
    if src is None:
        return []

    result = []
    for state_code, coord in coords.items():
        if state_code == str(requesting_state):
            continue
        distance = haversine_km(src[0], src[1], coord[0], coord[1])
        result.append({"state_code": state_code, "distance_km": distance})

    result.sort(key=lambda row: row["distance_km"])
    return result[: max(1, int(limit))]


def create_mutual_aid_request(
    db: Session,
    requesting_state: str,
    requesting_district: str,
    resource_id: str,
    quantity_requested: float,
    time: int,
) -> MutualAidRequest:
    row = MutualAidRequest(
        requesting_state=str(requesting_state),
        requesting_district=str(requesting_district),
        resource_id=str(resource_id),
        quantity_requested=max(0.0, float(quantity_requested)),
        time=int(time),
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_requests_from_unmet_allocations(db: Session, solver_run_id: int) -> int:
    unmet_rows = db.query(Allocation).filter(
        Allocation.solver_run_id == int(solver_run_id),
        Allocation.is_unmet == True,
    ).all()

    created = 0
    for row in unmet_rows:
        if float(row.allocated_quantity or 0.0) <= 1e-9:
            continue

        exists = db.query(MutualAidRequest).filter(
            MutualAidRequest.requesting_state == str(row.state_code),
            MutualAidRequest.requesting_district == str(row.district_code),
            MutualAidRequest.resource_id == str(row.resource_id),
            MutualAidRequest.time == int(row.time),
            MutualAidRequest.status.in_(list(REQUEST_OPEN_STATUSES)),
        ).first()
        if exists is not None:
            continue

        db.add(MutualAidRequest(
            requesting_state=str(row.state_code),
            requesting_district=str(row.district_code),
            resource_id=str(row.resource_id),
            quantity_requested=float(row.allocated_quantity),
            time=int(row.time),
            status="open",
        ))
        created += 1

    if created > 0:
        db.commit()
    return created


def _accepted_total(db: Session, request_id: int) -> float:
    value = db.query(func.coalesce(func.sum(MutualAidOffer.quantity_offered), 0.0)).filter(
        MutualAidOffer.request_id == int(request_id),
        MutualAidOffer.status == "accepted",
    ).scalar()
    return float(value or 0.0)


def _refresh_request_status(db: Session, request_id: int) -> MutualAidRequest | None:
    req = db.query(MutualAidRequest).filter(MutualAidRequest.id == int(request_id)).first()
    if req is None:
        return None

    accepted_total = _accepted_total(db, request_id=int(req.id))
    requested = float(req.quantity_requested or 0.0)

    if accepted_total <= 1e-9:
        req.status = "open"
    elif accepted_total + 1e-9 < requested:
        req.status = "partially_filled"
    else:
        req.status = "satisfied"
        db.query(MutualAidOffer).filter(
            MutualAidOffer.request_id == int(req.id),
            MutualAidOffer.status == "pending",
        ).update({"status": "revoked"}, synchronize_session=False)

    return req


def create_mutual_aid_offer(
    db: Session,
    request_id: int,
    offering_state: str,
    quantity_offered: float,
    cap_quantity: float | None = None,
) -> MutualAidOffer:
    req = db.query(MutualAidRequest).filter(MutualAidRequest.id == int(request_id)).first()
    if req is None:
        raise ValueError("Mutual aid request not found")

    if req.status in REQUEST_FINAL_STATUSES:
        raise ValueError("Mutual aid request is closed")

    if str(offering_state) == str(req.requesting_state):
        raise ValueError("Requesting state cannot self-offer")

    offered = max(0.0, float(quantity_offered))
    if cap_quantity is not None:
        offered = min(offered, max(0.0, float(cap_quantity)))

    row = MutualAidOffer(
        request_id=int(request_id),
        offering_state=str(offering_state),
        quantity_offered=offered,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def respond_to_offer(
    db: Session,
    offer_id: int,
    decision: str,
    actor_state: str,
) -> MutualAidOffer:
    offer = db.query(MutualAidOffer).filter(MutualAidOffer.id == int(offer_id)).first()
    if offer is None:
        raise ValueError("Offer not found")

    req = db.query(MutualAidRequest).filter(MutualAidRequest.id == int(offer.request_id)).first()
    if req is None:
        raise ValueError("Mutual aid request not found")

    raw = str(decision or "").strip().lower()
    if raw not in {"accepted", "rejected", "revoked"}:
        raise ValueError("Invalid offer decision")

    if raw == "accepted":
        if str(actor_state) != str(req.requesting_state):
            raise ValueError("Only requesting state can accept offers")
    elif raw == "revoked":
        if str(actor_state) != str(offer.offering_state):
            raise ValueError("Only offering state can revoke its offer")
    else:
        if str(actor_state) != str(req.requesting_state):
            raise ValueError("Only requesting state can reject offers")

    if str(offer.status) not in {"pending", "accepted"}:
        raise ValueError("Offer is no longer actionable")

    offer.status = raw
    db.flush()

    if raw == "accepted":
        exists = db.query(StateTransfer).filter(
            StateTransfer.offer_id == int(offer.id),
            StateTransfer.transfer_kind == "aid",
        ).first()
        if exists is None:
            db.add(StateTransfer(
                solver_run_id=None,
                request_id=int(req.id),
                offer_id=int(offer.id),
                from_state=str(offer.offering_state),
                to_state=str(req.requesting_state),
                resource_id=str(req.resource_id),
                quantity=float(offer.quantity_offered or 0.0),
                time=int(req.time),
                status="confirmed",
                transfer_kind="aid",
            ))

    _refresh_request_status(db, int(req.id))
    db.commit()
    db.refresh(offer)
    return offer


def list_requests_for_state(db: Session, state_code: str, include_closed: bool = False) -> list[MutualAidRequest]:
    query = db.query(MutualAidRequest).filter(MutualAidRequest.requesting_state == str(state_code))
    if not include_closed:
        query = query.filter(MutualAidRequest.status.in_(list(REQUEST_OPEN_STATUSES | {"satisfied"})))
    return query.order_by(MutualAidRequest.id.desc()).all()


def list_market_requests_for_offering_state(db: Session, offering_state: str) -> list[dict]:
    rows = db.query(MutualAidRequest).filter(
        MutualAidRequest.requesting_state != str(offering_state),
        MutualAidRequest.status.in_(list(REQUEST_OPEN_STATUSES)),
    ).order_by(MutualAidRequest.id.desc()).all()

    out = []
    for row in rows:
        accepted = _accepted_total(db, int(row.id))
        remaining = max(0.0, float(row.quantity_requested or 0.0) - accepted)
        out.append({
            "id": int(row.id),
            "requesting_state": row.requesting_state,
            "requesting_district": row.requesting_district,
            "resource_id": row.resource_id,
            "time": int(row.time),
            "quantity_requested": float(row.quantity_requested or 0.0),
            "accepted_quantity": accepted,
            "remaining_quantity": remaining,
            "status": row.status,
            "neighbors": get_candidate_states(db, requesting_state=str(row.requesting_state), limit=10),
        })
    return out


def build_state_stock_with_confirmed_transfers(
    db: Session,
    base_state_stock_path: Path,
    output_path: Path,
) -> str | None:
    if not base_state_stock_path.exists():
        return None

    base_df = pd.read_csv(base_state_stock_path)
    if base_df.empty:
        return None

    required = {"state_code", "resource_id", "quantity"}
    if not required.issubset(base_df.columns):
        return None

    base_df = base_df.copy()
    base_df["state_code"] = base_df["state_code"].astype(str)
    base_df["resource_id"] = base_df["resource_id"].astype(str)
    base_df["quantity"] = base_df["quantity"].astype(float)

    confirmed = db.query(
        StateTransfer.to_state,
        StateTransfer.resource_id,
        func.coalesce(func.sum(StateTransfer.quantity), 0.0).label("quantity"),
    ).filter(
        StateTransfer.transfer_kind == "aid",
        StateTransfer.status == "confirmed",
        (StateTransfer.consumed_in_run_id.is_(None)),
    ).group_by(
        StateTransfer.to_state,
        StateTransfer.resource_id,
    ).all()

    if not confirmed:
        return None

    transfer_df = pd.DataFrame([
        {
            "state_code": str(row.to_state),
            "resource_id": str(row.resource_id),
            "quantity": float(row.quantity or 0.0),
        }
        for row in confirmed
        if float(row.quantity or 0.0) > 1e-9
    ])

    if transfer_df.empty:
        return None

    combined = pd.concat([base_df, transfer_df], ignore_index=True)
    combined = combined.groupby(["state_code", "resource_id"], as_index=False)["quantity"].sum()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)
    return str(output_path)


def mark_confirmed_transfers_consumed(db: Session, solver_run_id: int):
    db.query(StateTransfer).filter(
        StateTransfer.transfer_kind == "aid",
        StateTransfer.status == "confirmed",
        StateTransfer.consumed_in_run_id.is_(None),
    ).update({"consumed_in_run_id": int(solver_run_id), "solver_run_id": int(solver_run_id)}, synchronize_session=False)
    db.commit()


def apply_transfer_provenance_to_run(db: Session, solver_run_id: int):
    transfer_rows = db.query(StateTransfer).filter(
        StateTransfer.transfer_kind == "aid",
        StateTransfer.status == "confirmed",
        StateTransfer.consumed_in_run_id == int(solver_run_id),
    ).all()
    if not transfer_rows:
        return

    transfer_map: dict[tuple[str, str, int], list[dict]] = {}
    for row in transfer_rows:
        key = (str(row.to_state), str(row.resource_id), int(row.time))
        transfer_map.setdefault(key, []).append({
            "origin": str(row.from_state),
            "remaining": float(row.quantity or 0.0),
        })

    alloc_rows = db.query(Allocation).filter(
        Allocation.solver_run_id == int(solver_run_id),
        Allocation.is_unmet == False,
    ).order_by(Allocation.id.asc()).all()

    inserts: list[Allocation] = []

    def _default_scope_and_code(row: Allocation, target_state: str) -> tuple[str, str]:
        level = str(row.supply_level or "district").lower()
        if level == "national":
            return ("national", "NATIONAL")
        if level == "state":
            origin = str(row.origin_state_code or target_state)
            if origin != target_state:
                return ("neighbor_state", origin)
            return ("state", origin)
        return ("district", str(row.district_code))

    for row in alloc_rows:
        target_state = str(row.state_code or "")
        resource_id = str(row.resource_id)
        key = (target_state, resource_id, int(row.time))
        options = transfer_map.get(key, [])

        if not options:
            if not str(row.origin_state_code or "").strip():
                row.origin_state = target_state
                row.origin_state_code = target_state
            if not str(row.allocation_source_scope or "").strip() or not str(row.allocation_source_code or "").strip():
                scope, code = _default_scope_and_code(row, target_state)
                row.allocation_source_scope = scope
                row.allocation_source_code = code
            row.implied_delay_hours = _implied_delay_hours(db, target_state, target_state)
            continue

        qty = float(row.allocated_quantity or 0.0)
        transfer_used = 0.0
        selected_origin = None

        for item in options:
            if qty <= 1e-9:
                break
            available = float(item["remaining"])
            if available <= 1e-9:
                continue
            take = min(qty, available)
            if take <= 1e-9:
                continue

            item["remaining"] = available - take
            qty -= take
            transfer_used += take
            selected_origin = str(item["origin"])

            if take > 1e-9 and qty > 1e-9:
                inserts.append(Allocation(
                    solver_run_id=int(row.solver_run_id),
                    request_id=int(row.request_id or 0),
                    source_request_id=(None if row.source_request_id is None else int(row.source_request_id)),
                    source_request_created_at=row.source_request_created_at,
                    source_batch_id=(None if row.source_batch_id is None else int(row.source_batch_id)),
                    resource_id=str(row.resource_id),
                    supply_level="state",
                    allocation_source_scope=("neighbor_state" if str(item["origin"]) != target_state else "state"),
                    allocation_source_code=str(item["origin"]),
                    district_code=str(row.district_code),
                    state_code=str(row.state_code),
                    origin_state=str(item["origin"]),
                    origin_state_code=str(item["origin"]),
                    origin_district_code=None,
                    time=int(row.time),
                    allocated_quantity=float(take),
                    implied_delay_hours=_implied_delay_hours(db, str(item["origin"]), target_state),
                    receipt_confirmed=False,
                    receipt_time=None,
                    is_unmet=bool(row.is_unmet),
                    claimed_quantity=float(row.claimed_quantity or 0.0),
                    consumed_quantity=float(row.consumed_quantity or 0.0),
                    returned_quantity=float(row.returned_quantity or 0.0),
                    status=str(row.status),
                ))

        if transfer_used <= 1e-9:
            if not str(row.origin_state_code or "").strip():
                row.origin_state = target_state
                row.origin_state_code = target_state
            if not str(row.allocation_source_scope or "").strip() or not str(row.allocation_source_code or "").strip():
                scope, code = _default_scope_and_code(row, target_state)
                row.allocation_source_scope = scope
                row.allocation_source_code = code
            row.implied_delay_hours = _implied_delay_hours(db, target_state, target_state)
            continue

        local_qty = float(row.allocated_quantity or 0.0) - transfer_used
        if local_qty <= 1e-9:
            row.origin_state = selected_origin or target_state
            row.origin_state_code = selected_origin or target_state
            row.allocation_source_scope = "neighbor_state" if (selected_origin and str(selected_origin) != target_state) else "state"
            row.allocation_source_code = str(row.origin_state_code or target_state)
            row.implied_delay_hours = _implied_delay_hours(db, row.origin_state_code, target_state)
        else:
            row.allocated_quantity = local_qty
            row.origin_state = target_state
            row.origin_state_code = target_state
            row.allocation_source_scope = "state" if str(row.supply_level or "").lower() == "state" else "district"
            row.allocation_source_code = str(target_state if str(row.supply_level or "").lower() == "state" else row.district_code)
            row.implied_delay_hours = _implied_delay_hours(db, target_state, target_state)

    if inserts:
        db.bulk_save_objects(inserts)

    db.commit()


def resolve_primary_origin_state_for_slot(
    db: Session,
    solver_run_id: int,
    district_code: str,
    state_code: str,
    resource_id: str,
    time: int,
) -> str:
    rows = db.query(
        Allocation.origin_state,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("qty"),
    ).filter(
        Allocation.solver_run_id == int(solver_run_id),
        Allocation.district_code == str(district_code),
        Allocation.resource_id == str(resource_id),
        Allocation.time == int(time),
        Allocation.is_unmet == False,
    ).group_by(Allocation.origin_state).all()

    if not rows:
        return str(state_code)

    ranked = sorted(
        [
            (str(row.origin_state or state_code), float(row.qty or 0.0))
            for row in rows
            if float(row.qty or 0.0) > 1e-9
        ],
        key=lambda item: item[1],
        reverse=True,
    )

    if not ranked:
        return str(state_code)

    for origin_state, _qty in ranked:
        if origin_state != str(state_code):
            return origin_state
    return str(state_code)


def record_return_transfer(
    db: Session,
    solver_run_id: int,
    from_state: str,
    to_state: str,
    resource_id: str,
    time: int,
    quantity: float,
):
    db.add(StateTransfer(
        solver_run_id=int(solver_run_id),
        request_id=None,
        offer_id=None,
        from_state=str(from_state),
        to_state=str(to_state),
        resource_id=str(resource_id),
        quantity=max(0.0, float(quantity)),
        time=int(time),
        status="confirmed",
        transfer_kind="return",
        consumed_in_run_id=None,
    ))
    db.flush()
