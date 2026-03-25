from __future__ import annotations

import hashlib
import os
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.allocation import Allocation
from app.models.mutual_aid_offer import MutualAidOffer
from app.models.mutual_aid_request import MutualAidRequest
from app.models.pool_transaction import PoolTransaction
from app.models.solver_run import SolverRun
from app.models.state import State
from app.models.state_transfer import StateTransfer
from app.config import AVG_SPEED_KMPH
from app.services.audit_service import log_event


REQUEST_OPEN_STATUSES = {"open", "partially_filled"}
REQUEST_FINAL_STATUSES = {"satisfied", "cancelled"}
OFFER_OPEN_STATUSES = {"pending"}
OFFER_ACCEPTED_STATUSES = {"accepted"}

AUTO_ESCALATION_MIN_UNMET_QTY = float(os.getenv("AUTO_ESCALATION_MIN_UNMET_QTY", "1"))
AUTO_ESCALATION_IMMEDIATE_TIME_MAX = int(os.getenv("AUTO_ESCALATION_IMMEDIATE_TIME_MAX", "0"))
AUTO_ESCALATION_NATIONAL_UNMET_RATIO = float(os.getenv("AUTO_ESCALATION_NATIONAL_UNMET_RATIO", "0.40"))
AUTO_ESCALATION_NEIGHBOR_MAX_STATES = int(os.getenv("AUTO_ESCALATION_NEIGHBOR_MAX_STATES", "5"))
AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION = float(os.getenv("AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION", "0.55"))
AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP = float(os.getenv("AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP", "0.20"))
AUTO_ESCALATION_NEIGHBOR_ACCEPT_THRESHOLD = int(os.getenv("AUTO_ESCALATION_NEIGHBOR_ACCEPT_THRESHOLD", "55"))
AUTO_ESCALATION_NEIGHBOR_EMERGENCY_ACCEPT_THRESHOLD = int(os.getenv("AUTO_ESCALATION_NEIGHBOR_EMERGENCY_ACCEPT_THRESHOLD", "75"))
AUTO_ESCALATION_NEIGHBOR_AUTO_ACCEPT = os.getenv("AUTO_ESCALATION_NEIGHBOR_AUTO_ACCEPT", "true").strip().lower() in {"1", "true", "yes", "on"}

AUTO_APPROVAL_SOURCES = {"scenario_auto", "auto_neighbor_chain", "scenario_auto_chain"}


def _normalize_solver_run_mode(mode: str | None) -> str:
    raw = str(mode or "").strip().lower()
    if raw == "normal":
        return "manual"
    if raw == "prod":
        return "production"
    if raw in {"scenario", "live", "production", "manual"}:
        return raw
    return "manual"


def _stable_acceptance_score(request_id: int, offering_state: str) -> int:
    token = f"{int(request_id)}:{str(offering_state)}".encode("utf-8")
    digest = hashlib.sha256(token).hexdigest()[:8]
    return int(digest, 16) % 100


def _state_resource_stock(
    db: Session,
    state_code: str,
    resource_id: str,
    cache: dict[tuple[str, str], float],
) -> float:
    key = (str(state_code), str(resource_id))
    if key in cache:
        return float(cache[key])

    from app.services.kpi_service import get_state_stock_rows

    state_rows_key = ("__state_rows__", str(state_code))
    value = 0.0
    try:
        state_map = cache.get(state_rows_key)  # type: ignore[assignment]
        if not isinstance(state_map, dict):
            rows = get_state_stock_rows(db, str(state_code))
            state_map = {
                str(row.get("resource_id") or ""): max(0.0, float(row.get("state_stock") or 0.0))
                for row in rows
            }
            cache[state_rows_key] = state_map  # type: ignore[assignment]
        value = float(state_map.get(str(resource_id), 0.0))
    except Exception:
        value = 0.0

    cache[key] = float(value)
    return float(value)


def auto_progress_mutual_aid_for_solver_run(db: Session, solver_run_id: int, run_mode: str | None = None) -> dict[str, int | float]:
    resolved_run_mode = _normalize_solver_run_mode(run_mode)
    if run_mode is None:
        run_row = db.query(SolverRun).filter(SolverRun.id == int(solver_run_id)).first()
        if run_row is not None:
            resolved_run_mode = _normalize_solver_run_mode(getattr(run_row, "mode", None))
    is_scenario_mode = resolved_run_mode == "scenario"

    unmet_rows = db.query(Allocation).filter(
        Allocation.solver_run_id == int(solver_run_id),
        Allocation.is_unmet == True,
    ).all()

    if not unmet_rows:
        return {
            "state_marked": 0,
            "national_marked": 0,
            "neighbor_offers_created": 0,
            "neighbor_offers_accepted": 0,
            "neighbor_accepted_quantity": 0.0,
        }

    unmet_map: dict[tuple[str, str, str, int], float] = {}
    for row in unmet_rows:
        qty = float(row.allocated_quantity or 0.0)
        if qty <= 1e-9:
            continue
        key = (str(row.state_code), str(row.district_code), str(row.resource_id), int(row.time))
        unmet_map[key] = unmet_map.get(key, 0.0) + qty

    open_reqs = db.query(MutualAidRequest).filter(
        MutualAidRequest.status.in_(list(REQUEST_OPEN_STATUSES)),
    ).all()
    req_map: dict[tuple[str, str, str, int], MutualAidRequest] = {
        (str(r.requesting_state), str(r.requesting_district), str(r.resource_id), int(r.time)): r
        for r in open_reqs
    }

    state_marked = 0
    national_marked = 0
    offers_created = 0
    offers_accepted = 0
    accepted_qty = 0.0

    max_states = max(1, int(AUTO_ESCALATION_NEIGHBOR_MAX_STATES))
    offer_fraction = max(0.05, min(1.0, float(AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION)))
    stock_cap = max(0.05, min(1.0, float(AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP)))
    stock_cache: dict[tuple[str, str], float] = {}

    for key, unmet_qty in unmet_map.items():
        requesting_state, requesting_district, resource_id, time_slot = key
        unmet_qty = float(unmet_qty)
        if unmet_qty < float(AUTO_ESCALATION_MIN_UNMET_QTY):
            continue

        req = req_map.get(key)
        if req is None:
            continue

        requested = max(float(req.quantity_requested or 0.0), unmet_qty)
        accepted_existing = _accepted_total(db, request_id=int(req.id))
        remaining = max(0.0, requested - accepted_existing)
        if remaining <= 1e-9:
            continue

        state_marked += 1
        unmet_ratio = (remaining / requested) if requested > 1e-9 else 1.0
        emergency_mode = (
            int(time_slot) <= int(AUTO_ESCALATION_IMMEDIATE_TIME_MAX)
            and unmet_ratio >= float(AUTO_ESCALATION_NATIONAL_UNMET_RATIO)
        )
        accept_threshold = int(
            AUTO_ESCALATION_NEIGHBOR_EMERGENCY_ACCEPT_THRESHOLD if emergency_mode else AUTO_ESCALATION_NEIGHBOR_ACCEPT_THRESHOLD
        )

        neighbors = get_candidate_states(db, requesting_state=requesting_state, limit=max_states * 2)
        used_states = 0
        for item in neighbors:
            if used_states >= max_states or remaining <= 1e-9:
                break
            offering_state = str(item.get("state_code") or "").strip()
            if not offering_state or offering_state == requesting_state:
                continue

            existing_offer = db.query(MutualAidOffer).filter(
                MutualAidOffer.request_id == int(req.id),
                MutualAidOffer.offering_state == offering_state,
                MutualAidOffer.status.in_(list(OFFER_OPEN_STATUSES | OFFER_ACCEPTED_STATUSES)),
            ).first()
            if existing_offer is not None:
                continue

            available_stock = _state_resource_stock(db, offering_state, resource_id, stock_cache)
            max_offer = max(0.0, available_stock * stock_cap)
            desired_offer = max(0.0, remaining * offer_fraction)
            offer_qty = min(max_offer, desired_offer)
            if offer_qty < float(AUTO_ESCALATION_MIN_UNMET_QTY):
                continue

            try:
                offer = create_mutual_aid_offer(
                    db=db,
                    request_id=int(req.id),
                    offering_state=offering_state,
                    quantity_offered=float(offer_qty),
                    cap_quantity=float(max_offer),
                    approval_source=("scenario_auto" if is_scenario_mode else "auto_neighbor_chain"),
                )
            except Exception:
                db.rollback()
                continue

            used_states += 1

            try:
                responded = respond_to_offer(
                    db=db,
                    offer_id=int(offer.id),
                    decision="accepted",
                    actor_state=str(requesting_state),
                    approval_source=("scenario_auto" if is_scenario_mode else "auto_neighbor_chain"),
                    auto_accepted=True,
                )
                if str(responded.status or "").lower() == "accepted":
                    qty = max(0.0, float(offer.quantity_offered or 0.0))
                    offers_accepted += 1
                    accepted_qty += qty
                    remaining = max(0.0, remaining - qty)
            except Exception:
                db.rollback()

        if remaining > float(AUTO_ESCALATION_MIN_UNMET_QTY):
            national_marked += 1

    if state_marked > 0:
        log_event(
            actor_role="system",
            actor_id="scenario_auto_escalation_orchestrator",
            event_type="AUTO_ESCALATED_TO_STATE_MARKET",
            payload={
                "solver_run_id": int(solver_run_id),
                "requests_marked": int(state_marked),
                "mutual_aid_requests_created": 0,
                "mode": ("scenario_auto_chain" if is_scenario_mode else "governed_chain"),
            },
            db=db,
        )

    if national_marked > 0:
        log_event(
            actor_role="system",
            actor_id="scenario_auto_escalation_orchestrator",
            event_type="AUTO_ESCALATED_TO_NATIONAL",
            payload={
                "solver_run_id": int(solver_run_id),
                "requests_marked": int(national_marked),
                "mode": ("scenario_auto_chain" if is_scenario_mode else "governed_chain"),
            },
            db=db,
        )

    if offers_created > 0:
        log_event(
            actor_role="system",
            actor_id="scenario_auto_escalation_orchestrator",
            event_type="AUTO_NEIGHBOR_OFFERS_SEEDED",
            payload={
                "solver_run_id": int(solver_run_id),
                "offers_created": int(offers_created),
                "offers_accepted": int(offers_accepted),
                "accepted_quantity": float(accepted_qty),
                "mode": ("scenario_auto_chain" if is_scenario_mode else "governed_chain"),
            },
            db=db,
        )

    db.commit()

    return {
        "state_marked": int(state_marked),
        "national_marked": int(national_marked),
        "neighbor_offers_created": int(offers_created),
        "neighbor_offers_accepted": int(offers_accepted),
        "neighbor_accepted_quantity": float(round(accepted_qty, 6)),
    }


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
        # Fallback for deployments without lat/lon metadata:
        # keep neighbor escalation usable by returning other states in stable code order.
        rows = db.query(State.state_code).filter(State.state_code != str(requesting_state)).order_by(State.state_code.asc()).all()
        out = [{"state_code": str(r[0]), "distance_km": None} for r in rows if r and str(r[0]).strip()]
        return out[: max(1, int(limit))]

    result = []
    for state_code, coord in coords.items():
        if state_code == str(requesting_state):
            continue
        distance = haversine_km(src[0], src[1], coord[0], coord[1])
        result.append({"state_code": state_code, "distance_km": distance})

    # If only a partial coordinate set is present, include remaining states as fallback tails.
    seen = {str(item.get("state_code") or "") for item in result}
    extra_rows = db.query(State.state_code).filter(State.state_code != str(requesting_state)).order_by(State.state_code.asc()).all()
    for row in extra_rows:
        state_code = str(row[0]) if row and row[0] is not None else ""
        if not state_code or state_code in seen:
            continue
        result.append({"state_code": state_code, "distance_km": None})

    result.sort(key=lambda row: (10**12 if row.get("distance_km") is None else float(row["distance_km"])))
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
    approval_source: str | None = None,
) -> MutualAidOffer:
    req = db.query(MutualAidRequest).filter(MutualAidRequest.id == int(request_id)).first()
    if req is None:
        raise ValueError("Mutual aid request not found")

    if req.status in REQUEST_FINAL_STATUSES:
        raise ValueError("Mutual aid request is closed")

    if str(offering_state) == str(req.requesting_state):
        raise ValueError("Requesting state cannot self-offer")

    requested = float(req.quantity_requested or 0.0)
    accepted_total = _accepted_total(db, request_id)
    remaining = max(0.0, requested - accepted_total)
    
    if remaining <= 0:
        req.status = "satisfied"
        db.commit()
        raise ValueError("Mutual aid request is already satisfied")

    offered = max(0.0, float(quantity_offered))
    if cap_quantity is not None:
        offered = min(offered, max(0.0, float(cap_quantity)))
        
    offered = min(offered, remaining)
    
    if offered <= 0:
        raise ValueError("Offer quantity must be greater than 0")

    row = MutualAidOffer(
        request_id=int(request_id),
        offering_state=str(offering_state),
        quantity_offered=offered,
        status="pending",
        auto_accepted=0,
        approval_source=str(approval_source or "state_authority"),
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
    approval_source: str | None = None,
    auto_accepted: bool = False,
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

    effective_auto_accept = bool(auto_accepted) and (
        str(offer.approval_source or "").strip() in AUTO_APPROVAL_SOURCES
        or str(approval_source or "").strip() in AUTO_APPROVAL_SOURCES
    )

    offer.status = raw
    if raw == "accepted":
        offer.auto_accepted = int(1 if effective_auto_accept else 0)
    else:
        offer.auto_accepted = 0
    if approval_source is not None:
        offer.approval_source = str(approval_source)
    elif raw == "accepted":
        offer.approval_source = "scenario_auto" if bool(auto_accepted) else "state_authority"
    elif str(offer.approval_source or "").strip() == "":
        offer.approval_source = "state_authority"
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
            db.add(PoolTransaction(
                state_code=str(offer.offering_state),
                resource_id=str(req.resource_id),
                time=int(req.time),
                quantity_delta=-float(offer.quantity_offered or 0.0),
                reason=f"mutual_aid_offer:{offer.id}",
                actor_role="state_admin",
                actor_id=str(actor_state),
            ))
            db.add(PoolTransaction(
                state_code=str(req.requesting_state),
                resource_id=str(req.resource_id),
                time=int(req.time),
                quantity_delta=float(offer.quantity_offered or 0.0),
                reason=f"mutual_aid_receive:{offer.id}",
                actor_role="state_admin",
                actor_id=str(actor_state),
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
