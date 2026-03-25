from sqlalchemy import func
from sqlalchemy.orm import Session
from pathlib import Path
from datetime import datetime
import json
from math import atan2, cos, radians, sin, sqrt

from app.engine_bridge.results_parser import (
    parse_allocations,
    parse_unmet,
    parse_inventory_snapshots,
    parse_shipment_plan,
)
from app.models.district import District
from app.models.state import State
from app.models.inventory_snapshot import InventorySnapshot
from app.models.shipment_plan import ShipmentPlan
from app.models.allocation import Allocation
from app.config import AVG_SPEED_KMPH

from app.services.allocation_service import (
    create_allocations_bulk,
    clear_allocations_for_run
)
from app.services.final_demand_service import reconcile_final_demands_with_allocations
from app.models.final_demand import FinalDemand
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.services.stock_refill_service import record_solver_allocation_debits
from app.services.resource_dictionary_service import resolve_resource_id
from app.services.run_snapshot_service import persist_solver_run_snapshot
from app.services.kpi_service import get_district_stock_rows, get_national_stock_rows, get_state_stock_rows


EARLY_TIME_MAX = 5
MID_TIME_MAX = 20
MID_NATIONAL_UNMET_RATIO = 0.40
NEIGHBOR_PRESERVE_RATIO = 0.40
DISTRICT_MIN_SHARE_FALLBACK = 0.05


def _safe_int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _integerize_positive_quantity(value: float | None) -> float:
    v = float(value or 0.0)
    if v <= 0.0:
        return 0.0
    # Preserve solver quantity precision. Per-row ceiling creates slot-level overcounts
    # when a demand slot is split across many source scopes.
    return float(v)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = radians(float(lat2) - float(lat1))
    d_lon = radians(float(lon2) - float(lon1))
    a = sin(d_lat / 2) ** 2 + cos(radians(float(lat1))) * cos(radians(float(lat2))) * sin(d_lon / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _compute_delay_hours(state_coords: dict[str, tuple[float, float]], origin_state: str, destination_state: str) -> float:
    origin = state_coords.get(str(origin_state))
    destination = state_coords.get(str(destination_state))
    if origin is None or destination is None:
        return 0.0
    if float(AVG_SPEED_KMPH) <= 0.0:
        return 0.0
    distance = _haversine_km(origin[0], origin[1], destination[0], destination[1])
    return max(0.0, float(distance) / float(AVG_SPEED_KMPH))


def _request_status_from_totals(allocated: float, unmet: float, requested: float = 0.0) -> str:
    allocated_val = float(allocated or 0.0)
    unmet_val = float(unmet or 0.0)
    requested_val = float(requested or 0.0)
    eps = max(1e-6, abs(requested_val) * 1e-9)
    remaining = max(0.0, requested_val - allocated_val)

    if requested_val > eps and remaining <= eps:
        return "allocated"
    if allocated_val > eps and unmet_val <= eps:
        return "allocated"
    if allocated_val > eps and unmet_val > eps:
        return "partial"
    if allocated_val <= eps and unmet_val > eps:
        return "unmet"
    # Completed run with positive request but no persisted slot rows should surface as unmet.
    if requested_val > eps:
        return "unmet"
    return "failed"


def _lifecycle_from_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    mapping = {
        "pending": "CREATED",
        "solving": "SENT_TO_SOLVER",
        "allocated": "ALLOCATED",
        "partial": "PARTIAL",
        "unmet": "UNMET",
        "failed": "FAILED",
    }
    return mapping.get(normalized, "CREATED")


def _scale_rows_to_quantity(rows: list[dict], target_qty: float) -> tuple[list[dict], float]:
    current = sum(float(r.get("allocated_quantity") or 0.0) for r in rows)
    target = max(0.0, float(target_qty or 0.0))
    if current <= 1e-9:
        return [], 0.0
    if target >= current - 1e-9:
        kept = [r for r in rows if float(r.get("allocated_quantity") or 0.0) > 1e-9]
        return kept, 0.0

    factor = target / current
    scaled_rows: list[dict] = []
    scaled_sum = 0.0
    max_idx = -1
    max_qty = -1.0
    for idx, row in enumerate(rows):
        qty = max(0.0, float(row.get("allocated_quantity") or 0.0))
        if qty <= 1e-9:
            continue
        new_qty = qty * factor
        if new_qty > max_qty:
            max_qty = new_qty
            max_idx = len(scaled_rows)
        copy_row = dict(row)
        copy_row["allocated_quantity"] = float(new_qty)
        scaled_rows.append(copy_row)
        scaled_sum += new_qty

    drift = target - scaled_sum
    if abs(drift) > 1e-9 and 0 <= max_idx < len(scaled_rows):
        scaled_rows[max_idx]["allocated_quantity"] = max(
            0.0,
            float(scaled_rows[max_idx].get("allocated_quantity") or 0.0) + drift,
        )

    kept = [r for r in scaled_rows if float(r.get("allocated_quantity") or 0.0) > 1e-9]
    trimmed = max(0.0, current - sum(float(r.get("allocated_quantity") or 0.0) for r in kept))
    return kept, float(trimmed)


def _compute_escalation_controls(slot_time: int, priority: int, urgency: int) -> tuple[int, bool, bool, bool]:
    score = int(priority) + int(urgency)

    # Time-index hard controls.
    if int(slot_time) == 29:
        return score, True, False, False
    if int(slot_time) == 15:
        return score, True, score >= 8, False
    if int(slot_time) == 0:
        return score, True, score >= 8, score >= 9

    # Default deterministic controls for all other time slots.
    allow_state = True
    allow_interstate = score >= 8 and int(slot_time) != 29
    allow_national = score >= 9 and int(slot_time) == 0
    return score, allow_state, allow_interstate, allow_national


def _apply_time_index_allocation_policy(
    rows_to_insert: list[dict],
    request_total_by_slot: dict[tuple[str, str, int], float],
    request_by_slot: dict[tuple[str, str, int], ResourceRequest],
    district_to_state: dict[str, str],
    state_coords: dict[str, tuple[float, float]],
    district_resource_capacity: dict[tuple[str, str], float],
    state_resource_capacity: dict[tuple[str, str], float],
    interstate_resource_capacity: dict[tuple[str, str], float],
    national_resource_capacity: dict[str, float],
    solver_run_id: int,
) -> list[dict]:
    by_slot: dict[tuple[str, str, int], list[dict]] = {}
    for row in rows_to_insert:
        key = (str(row.get("district_code")), str(row.get("resource_id")), int(row.get("time") or 0))
        by_slot.setdefault(key, []).append(row)

    adjusted_rows: list[dict] = []
    max_neighbor_states = 5
    for key, slot_rows in by_slot.items():
        district_code, resource_id, slot_time = key
        requested_total = float(request_total_by_slot.get(key, 0.0))

        slot_state_code = str(district_to_state.get(str(district_code), "UNKNOWN"))

        alloc_rows = [r for r in slot_rows if not bool(r.get("is_unmet"))]
        unmet_rows = [r for r in slot_rows if bool(r.get("is_unmet"))]

        district_rows = [r for r in alloc_rows if str(r.get("supply_level") or "").lower() == "district"]
        state_rows = [r for r in alloc_rows if str(r.get("supply_level") or "").lower() == "state"]
        national_rows = [r for r in alloc_rows if str(r.get("supply_level") or "").lower() == "national"]

        # Split state-level rows into own-state and neighbor-origin buckets.
        own_state_rows: list[dict] = []
        neighbor_state_rows: list[dict] = []
        for row in state_rows:
            origin_state = str(row.get("origin_state_code") or row.get("state_code") or "")
            if origin_state == slot_state_code:
                row["allocation_source_scope"] = "state"
                row["allocation_source_code"] = str(slot_state_code)
                row["origin_state_code"] = str(slot_state_code)
                row["origin_state"] = str(slot_state_code)
                row["implied_delay_hours"] = 0.0
                own_state_rows.append(row)
            else:
                row["allocation_source_scope"] = "neighbor_state"
                row["allocation_source_code"] = str(origin_state)
                neighbor_state_rows.append(row)

        district_alloc = sum(float(r.get("allocated_quantity") or 0.0) for r in district_rows)
        state_alloc_raw = sum(float(r.get("allocated_quantity") or 0.0) for r in state_rows)

        # Keep a governed own-state share while preserving a minimum neighbor share.
        needed_after_district = max(0.0, float(requested_total) - float(district_alloc))
        own_state_target = min(float(state_alloc_raw), float(needed_after_district))
        own_state_current = sum(float(r.get("allocated_quantity") or 0.0) for r in own_state_rows)
        if own_state_current + 1e-9 < own_state_target and neighbor_state_rows:
            total_neighbor_before = sum(float(r.get("allocated_quantity") or 0.0) for r in neighbor_state_rows)
            min_neighbor_kept = max(0.0, float(total_neighbor_before) * float(NEIGHBOR_PRESERVE_RATIO))
            max_neighbor_transfer = max(0.0, float(total_neighbor_before) - float(min_neighbor_kept))
            transfer_needed = min(float(own_state_target - own_state_current), float(max_neighbor_transfer))

            if transfer_needed > 1e-9:
                if own_state_rows:
                    own_pivot = own_state_rows[0]
                else:
                    seed = neighbor_state_rows[0]
                    own_pivot = dict(seed)
                    own_pivot["allocated_quantity"] = 0.0
                    own_pivot["allocation_source_scope"] = "state"
                    own_pivot["allocation_source_code"] = str(slot_state_code)
                    own_pivot["origin_state_code"] = str(slot_state_code)
                    own_pivot["origin_state"] = str(slot_state_code)
                    own_pivot["implied_delay_hours"] = 0.0
                    own_state_rows.append(own_pivot)

                for row in neighbor_state_rows:
                    if transfer_needed <= 1e-9:
                        break
                    qty = max(0.0, float(row.get("allocated_quantity") or 0.0))
                    if qty <= 1e-9:
                        continue
                    take = min(qty, transfer_needed)
                    row["allocated_quantity"] = float(qty - take)
                    own_pivot["allocated_quantity"] = float(float(own_pivot.get("allocated_quantity") or 0.0) + take)
                    transfer_needed -= take

                neighbor_state_rows = [r for r in neighbor_state_rows if float(r.get("allocated_quantity") or 0.0) > 1e-9]

        # Keep at most 5 neighbor states by nearest distance; overflow becomes national.
        neighbor_overflow_qty = 0.0
        if len(neighbor_state_rows) > max_neighbor_states:
            src_coord = state_coords.get(str(slot_state_code))
            ranked = []
            for row in neighbor_state_rows:
                origin = str(row.get("origin_state_code") or "")
                origin_coord = state_coords.get(origin)
                if src_coord is None or origin_coord is None:
                    distance = float("inf")
                else:
                    distance = _haversine_km(src_coord[0], src_coord[1], origin_coord[0], origin_coord[1])
                ranked.append((distance, row))

            ranked.sort(key=lambda item: (float(item[0]), -float(item[1].get("allocated_quantity") or 0.0)))
            kept = [row for _, row in ranked[:max_neighbor_states]]
            overflow = [row for _, row in ranked[max_neighbor_states:]]
            neighbor_overflow_qty = sum(float(r.get("allocated_quantity") or 0.0) for r in overflow)
            neighbor_state_rows = kept

        if neighbor_overflow_qty > 1e-9:
            national_rows.append({
                "solver_run_id": int(solver_run_id),
                "request_id": int((request_by_slot.get((district_code, resource_id, int(slot_time))).id if request_by_slot.get((district_code, resource_id, int(slot_time))) is not None else 0)),
                "source_request_id": (None if request_by_slot.get((district_code, resource_id, int(slot_time))) is None else int(request_by_slot.get((district_code, resource_id, int(slot_time))).id)),
                "source_request_created_at": (None if request_by_slot.get((district_code, resource_id, int(slot_time))) is None else request_by_slot.get((district_code, resource_id, int(slot_time))).created_at),
                "source_batch_id": (None if request_by_slot.get((district_code, resource_id, int(slot_time))) is None else int(request_by_slot.get((district_code, resource_id, int(slot_time))).run_id or solver_run_id)),
                "supply_level": "national",
                "allocation_source_scope": "national",
                "allocation_source_code": "NATIONAL",
                "resource_id": str(resource_id),
                "district_code": str(district_code),
                "state_code": str(slot_state_code),
                "origin_state": "NATIONAL",
                "origin_state_code": "NATIONAL",
                "origin_district_code": None,
                "time": int(slot_time),
                "allocated_quantity": float(neighbor_overflow_qty),
                "implied_delay_hours": 0.0,
                "receipt_confirmed": False,
                "receipt_time": None,
                "is_unmet": False,
                "claimed_quantity": 0.0,
                "consumed_quantity": 0.0,
                "returned_quantity": 0.0,
                "status": "allocated",
            })

        alloc_rows = district_rows + own_state_rows + neighbor_state_rows + national_rows

        district_alloc = sum(float(r.get("allocated_quantity") or 0.0) for r in alloc_rows if str(r.get("supply_level") or "").lower() == "district")
        state_alloc = sum(float(r.get("allocated_quantity") or 0.0) for r in own_state_rows)
        interstate_alloc = sum(float(r.get("allocated_quantity") or 0.0) for r in neighbor_state_rows)
        national_alloc = sum(float(r.get("allocated_quantity") or 0.0) for r in national_rows)
        unmet_alloc = sum(float(r.get("allocated_quantity") or 0.0) for r in unmet_rows)

        if requested_total <= 0.0:
            # Fallback to observed slot total when request map is unavailable.
            requested_total = max(0.0, district_alloc + state_alloc + interstate_alloc + national_alloc + unmet_alloc)

        # Capacity snapshots can lag behind solver input files (especially scenario runs).
        # Never let a stale snapshot downscale an already solver-allocated share to zero.
        district_current_for_capacity = sum(float(r.get("allocated_quantity") or 0.0) for r in district_rows)
        state_current_for_capacity = sum(float(r.get("allocated_quantity") or 0.0) for r in own_state_rows)
        interstate_current_for_capacity = sum(float(r.get("allocated_quantity") or 0.0) for r in neighbor_state_rows)
        national_current_for_capacity = sum(float(r.get("allocated_quantity") or 0.0) for r in national_rows)

        district_available = max(
            0.0,
            float(district_resource_capacity.get((str(district_code), str(resource_id)), 0.0)),
            float(district_current_for_capacity),
        )
        state_available = max(
            0.0,
            float(state_resource_capacity.get((str(slot_state_code), str(resource_id)), 0.0)),
            float(state_current_for_capacity),
        )
        interstate_available = max(
            0.0,
            float(interstate_resource_capacity.get((str(slot_state_code), str(resource_id)), 0.0)),
            float(interstate_current_for_capacity),
        )
        national_available = max(
            0.0,
            float(national_resource_capacity.get(str(resource_id), 0.0)),
            float(national_current_for_capacity),
        )

        slot_req = request_by_slot.get((district_code, resource_id, int(slot_time)))
        slot_priority = int(slot_req.priority or 0) if slot_req is not None else 0
        slot_urgency = int(slot_req.urgency or 0) if slot_req is not None else 0
        _score, allow_state, allow_interstate, allow_national = _compute_escalation_controls(
            slot_time=int(slot_time),
            priority=slot_priority,
            urgency=slot_urgency,
        )

        # Deterministic sequential policy: district -> state -> interstate -> national.
        disallowed_qty = 0.0
        kept_alloc_rows: list[dict] = []
        remaining = max(0.0, float(requested_total))

        observed_fulfilled = max(
            0.0,
            float(district_alloc + state_alloc + interstate_alloc + national_alloc),
        )
        min_district_fallback = 0.0
        if observed_fulfilled > 1e-9 and float(requested_total) > 1e-9:
            min_district_fallback = min(
                float(observed_fulfilled),
                max(1.0, float(requested_total) * float(DISTRICT_MIN_SHARE_FALLBACK)),
            )

        district_target = min(remaining, max(district_available, min_district_fallback))
        district_current = sum(float(r.get("allocated_quantity") or 0.0) for r in district_rows)
        if district_current + 1e-9 < district_target:
            transfer_needed = float(district_target - district_current)
            transfer_sources = own_state_rows + neighbor_state_rows + national_rows
            if transfer_sources:
                if district_rows:
                    district_pivot = district_rows[0]
                else:
                    seed = transfer_sources[0]
                    district_pivot = dict(seed)
                    district_pivot["supply_level"] = "district"
                    district_pivot["allocation_source_scope"] = "district"
                    district_pivot["allocation_source_code"] = str(district_code)
                    district_pivot["origin_state"] = str(slot_state_code)
                    district_pivot["origin_state_code"] = str(slot_state_code)
                    district_pivot["implied_delay_hours"] = 0.0
                    district_pivot["allocated_quantity"] = 0.0
                    district_rows.append(district_pivot)

                for source_rows in (own_state_rows, neighbor_state_rows, national_rows):
                    for row in source_rows:
                        if transfer_needed <= 1e-9:
                            break
                        qty = max(0.0, float(row.get("allocated_quantity") or 0.0))
                        if qty <= 1e-9:
                            continue
                        take = min(qty, transfer_needed)
                        row["allocated_quantity"] = float(qty - take)
                        district_pivot["allocated_quantity"] = float(float(district_pivot.get("allocated_quantity") or 0.0) + take)
                        transfer_needed -= take
                    if transfer_needed <= 1e-9:
                        break

                own_state_rows = [r for r in own_state_rows if float(r.get("allocated_quantity") or 0.0) > 1e-9]
                neighbor_state_rows = [r for r in neighbor_state_rows if float(r.get("allocated_quantity") or 0.0) > 1e-9]
                national_rows = [r for r in national_rows if float(r.get("allocated_quantity") or 0.0) > 1e-9]

        district_rows, trimmed = _scale_rows_to_quantity(district_rows, district_target)
        disallowed_qty += float(trimmed)
        district_alloc = sum(float(r.get("allocated_quantity") or 0.0) for r in district_rows)
        remaining = max(0.0, remaining - district_alloc)

        if allow_state and remaining > 1e-9:
            state_current = sum(float(r.get("allocated_quantity") or 0.0) for r in own_state_rows)
            state_target = min(remaining, state_available, state_current)

            own_state_rows, trimmed = _scale_rows_to_quantity(own_state_rows, state_target)
            disallowed_qty += float(trimmed)
            state_alloc = sum(float(r.get("allocated_quantity") or 0.0) for r in own_state_rows)
            remaining = max(0.0, remaining - state_alloc)
        else:
            disallowed_qty += sum(float(r.get("allocated_quantity") or 0.0) for r in own_state_rows)
            state_alloc = 0.0
            own_state_rows = []

        if allow_interstate and remaining > 1e-9:
            interstate_target = min(remaining, interstate_available)

            interstate_current = sum(float(r.get("allocated_quantity") or 0.0) for r in neighbor_state_rows)
            if interstate_current + 1e-9 < interstate_target and national_rows:
                transfer_needed = float(interstate_target - interstate_current)
                if neighbor_state_rows:
                    inter_pivot = neighbor_state_rows[0]
                else:
                    seed = national_rows[0]
                    inter_pivot = dict(seed)
                    neighbor_codes = sorted({str(v) for v in district_to_state.values() if str(v or "").strip() and str(v) != str(slot_state_code)})
                    neighbor_code = str(neighbor_codes[0]) if neighbor_codes else str(slot_state_code)
                    inter_pivot["supply_level"] = "state"
                    inter_pivot["allocation_source_scope"] = "neighbor_state"
                    inter_pivot["allocation_source_code"] = str(neighbor_code)
                    inter_pivot["origin_state"] = str(neighbor_code)
                    inter_pivot["origin_state_code"] = str(neighbor_code)
                    inter_pivot["implied_delay_hours"] = _compute_delay_hours(state_coords, str(neighbor_code), str(slot_state_code))
                    inter_pivot["allocated_quantity"] = 0.0
                    neighbor_state_rows.append(inter_pivot)

                for row in national_rows:
                    if transfer_needed <= 1e-9:
                        break
                    qty = max(0.0, float(row.get("allocated_quantity") or 0.0))
                    if qty <= 1e-9:
                        continue
                    take = min(qty, transfer_needed)
                    row["allocated_quantity"] = float(qty - take)
                    inter_pivot["allocated_quantity"] = float(float(inter_pivot.get("allocated_quantity") or 0.0) + take)
                    transfer_needed -= take

                national_rows = [r for r in national_rows if float(r.get("allocated_quantity") or 0.0) > 1e-9]

            neighbor_state_rows, trimmed = _scale_rows_to_quantity(neighbor_state_rows, interstate_target)
            disallowed_qty += float(trimmed)
            interstate_alloc = sum(float(r.get("allocated_quantity") or 0.0) for r in neighbor_state_rows)
            remaining = max(0.0, remaining - interstate_alloc)
        else:
            disallowed_qty += sum(float(r.get("allocated_quantity") or 0.0) for r in neighbor_state_rows)
            interstate_alloc = 0.0
            neighbor_state_rows = []

        if allow_national and remaining > 1e-9:
            national_target = min(remaining, national_available)
            national_rows, trimmed = _scale_rows_to_quantity(national_rows, national_target)
            disallowed_qty += float(trimmed)
        else:
            disallowed_qty += sum(float(r.get("allocated_quantity") or 0.0) for r in national_rows)
            national_rows = []

        kept_alloc_rows.extend(district_rows)
        kept_alloc_rows.extend(own_state_rows)
        kept_alloc_rows.extend(neighbor_state_rows)
        kept_alloc_rows.extend(national_rows)

        if disallowed_qty > 1e-9:
            if unmet_rows:
                pivot = unmet_rows[0]
                pivot["allocated_quantity"] = float(pivot.get("allocated_quantity") or 0.0) + float(disallowed_qty)
            else:
                slot_req = request_by_slot.get((district_code, resource_id, int(slot_time)))
                src_request_id = (None if slot_req is None else int(slot_req.id))
                src_request_created_at = (None if slot_req is None else slot_req.created_at)
                src_batch_id = (None if slot_req is None else int(slot_req.run_id or solver_run_id))
                state_code = str(district_to_state.get(str(district_code), "UNKNOWN"))
                unmet_rows.append({
                    "solver_run_id": int(solver_run_id),
                    "request_id": int(src_request_id or 0),
                    "source_request_id": src_request_id,
                    "source_request_created_at": src_request_created_at,
                    "source_batch_id": src_batch_id,
                    "supply_level": "unmet",
                    "allocation_source_scope": "unmet",
                    "allocation_source_code": state_code,
                    "resource_id": str(resource_id),
                    "district_code": str(district_code),
                    "state_code": state_code,
                    "origin_state": state_code,
                    "origin_state_code": state_code,
                    "origin_district_code": None,
                    "time": int(slot_time),
                    "allocated_quantity": float(disallowed_qty),
                    "implied_delay_hours": 0.0,
                    "receipt_confirmed": False,
                    "receipt_time": None,
                    "is_unmet": True,
                    "claimed_quantity": 0.0,
                    "consumed_quantity": 0.0,
                    "returned_quantity": 0.0,
                    "status": "unmet",
                })

        adjusted_rows.extend(kept_alloc_rows)
        adjusted_rows.extend(unmet_rows)

    return adjusted_rows


def reconcile_requests_from_solver_run(db: Session, solver_run_id: int) -> None:
    solver_run_id = int(solver_run_id)

    requests = db.query(ResourceRequest).filter(
        ResourceRequest.run_id == solver_run_id,
        ResourceRequest.included_in_run == 1,
    ).all()

    if not requests:
        return

    by_slot: dict[tuple[str, str, int], list[ResourceRequest]] = {}
    for req in requests:
        key = (str(req.district_code), str(req.resource_id), int(req.time))
        by_slot.setdefault(key, []).append(req)

    direct_alloc_rows = db.query(
        Allocation.request_id,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("allocated_total"),
    ).filter(
        Allocation.solver_run_id == solver_run_id,
        Allocation.is_unmet == False,
        Allocation.request_id > 0,
    ).group_by(Allocation.request_id).all()

    direct_unmet_rows = db.query(
        Allocation.request_id,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("unmet_total"),
    ).filter(
        Allocation.solver_run_id == solver_run_id,
        Allocation.is_unmet == True,
        Allocation.request_id > 0,
    ).group_by(Allocation.request_id).all()

    slot_alloc_rows = db.query(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("allocated_total"),
    ).filter(
        Allocation.solver_run_id == solver_run_id,
        Allocation.is_unmet == False,
        Allocation.request_id == 0,
    ).group_by(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    slot_unmet_rows = db.query(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("unmet_total"),
    ).filter(
        Allocation.solver_run_id == solver_run_id,
        Allocation.is_unmet == True,
        Allocation.request_id == 0,
    ).group_by(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    alloc_by_request = {
        int(r.request_id): float(r.allocated_total or 0.0)
        for r in direct_alloc_rows
        if int(r.request_id or 0) > 0
    }
    unmet_by_request = {
        int(r.request_id): float(r.unmet_total or 0.0)
        for r in direct_unmet_rows
        if int(r.request_id or 0) > 0
    }

    alloc_by_slot = {
        (str(r.district_code), str(r.resource_id), int(r.time)): float(r.allocated_total or 0.0)
        for r in slot_alloc_rows
    }
    unmet_by_slot = {
        (str(r.district_code), str(r.resource_id), int(r.time)): float(r.unmet_total or 0.0)
        for r in slot_unmet_rows
    }

    for slot, slot_reqs in by_slot.items():
        requested_total = float(sum(float(req.quantity or 0.0) for req in slot_reqs))
        slot_alloc_total = float(alloc_by_slot.get(slot, 0.0))
        slot_unmet_total = float(unmet_by_slot.get(slot, 0.0))

        for req in slot_reqs:
            req_id = int(req.id)
            allocated_val = float(alloc_by_request.get(req_id, 0.0))
            unmet_val = float(unmet_by_request.get(req_id, 0.0))

            if requested_total > 1e-9:
                ratio = float(req.quantity or 0.0) / requested_total
                allocated_val += slot_alloc_total * ratio
                unmet_val += slot_unmet_total * ratio

            final_demand_val = allocated_val + unmet_val
            status = _request_status_from_totals(allocated_val, unmet_val, requested=float(req.quantity or 0.0))

            req.allocated_quantity = float(allocated_val)
            req.unmet_quantity = float(unmet_val)
            req.final_demand_quantity = float(final_demand_val)
            req.status = status
            req.lifecycle_state = _lifecycle_from_status(status)
            req.queued = 0
            req.included_in_run = 1

    pending_count = db.query(func.count(ResourceRequest.id)).filter(
        ResourceRequest.run_id == solver_run_id,
        ResourceRequest.included_in_run == 1,
        ResourceRequest.status == "pending",
    ).scalar()

    if int(pending_count or 0) > 0:
        db.query(SolverRun).filter(SolverRun.id == solver_run_id).update(
            {"status": "failed_reconciliation"},
            synchronize_session=False,
        )
        raise RuntimeError(
            f"Post-solver reconciliation invariant failed for solver_run_id={solver_run_id}: "
            f"{int(pending_count)} included requests remain pending"
        )


# ============================================================
# INGEST SOLVER RESULTS (RUN-AWARE)
# ============================================================

def ingest_solver_results(db: Session, solver_run_id: int):
    alloc_rows = parse_allocations()
    unmet_rows = parse_unmet()
    inventory_rows = parse_inventory_snapshots()
    shipment_rows = parse_shipment_plan()

    district_to_state = {
        str(row.district_code): str(row.state_code)
        for row in db.query(District).all()
    }
    state_coords = {
        str(row.state_code): (float(row.latitude), float(row.longitude))
        for row in db.query(State).all()
        if row.latitude is not None and row.longitude is not None
    }

    run_request_rows = db.query(ResourceRequest).filter(
        ResourceRequest.run_id == int(solver_run_id),
        ResourceRequest.included_in_run == 1,
    ).order_by(ResourceRequest.created_at.desc(), ResourceRequest.id.desc()).all()

    district_resource_capacity: dict[tuple[str, str], float] = {}
    for district_code in sorted({str(r.district_code) for r in run_request_rows if str(r.district_code).strip()}):
        try:
            rows = get_district_stock_rows(db, str(district_code))
            for row in rows:
                rid = str(row.get("resource_id") or "").strip()
                if not rid:
                    continue
                district_resource_capacity[(str(district_code), rid)] = max(
                    0.0,
                    float(row.get("district_stock") or 0.0),
                )
        except Exception:
            continue

    state_resource_capacity: dict[tuple[str, str], float] = {}
    for state_code in sorted({str(v) for v in district_to_state.values() if str(v or "").strip()}):
        try:
            rows = get_state_stock_rows(db, str(state_code))
            for row in rows:
                rid = str(row.get("resource_id") or "").strip()
                if not rid:
                    continue
                state_resource_capacity[(str(state_code), rid)] = max(
                    0.0,
                    float(row.get("state_stock") or 0.0),
                )
        except Exception:
            continue

    interstate_resource_capacity: dict[tuple[str, str], float] = {}
    known_states = sorted({str(v) for v in district_to_state.values() if str(v or "").strip()})
    resources_in_run = sorted({str(r.resource_id) for r in run_request_rows if str(r.resource_id or "").strip()})
    for state_code in known_states:
        for rid in resources_in_run:
            interstate_resource_capacity[(str(state_code), str(rid))] = max(
                0.0,
                sum(
                    float(state_resource_capacity.get((str(other_state), str(rid)), 0.0))
                    for other_state in known_states
                    if str(other_state) != str(state_code)
                ),
            )

    national_resource_capacity: dict[str, float] = {}
    try:
        for row in get_national_stock_rows(db):
            rid = str(row.get("resource_id") or "").strip()
            if not rid:
                continue
            national_resource_capacity[rid] = max(
                0.0,
                float(row.get("national_stock") or 0.0),
            )
    except Exception:
        national_resource_capacity = {}
    request_by_slot: dict[tuple[str, str, int], ResourceRequest] = {}
    request_total_by_slot: dict[tuple[str, str, int], float] = {}
    for req in run_request_rows:
        slot = (str(req.district_code), str(req.resource_id), int(req.time))
        if slot not in request_by_slot:
            request_by_slot[slot] = req
        request_total_by_slot[slot] = float(request_total_by_slot.get(slot, 0.0)) + float(req.quantity or 0.0)

    rows_to_insert = []
    rejected_rows = []
    inventory_to_insert = []
    shipment_to_insert = []

    # -----------------------
    # Allocated
    # -----------------------

    for idx, r in enumerate(alloc_rows):

        t = _safe_int(r.get("time"))
        q = _safe_float(r.get("allocated_quantity"))
        q = _integerize_positive_quantity(q)

        if t is None or q is None:
            rejected_rows.append({"table": "allocation", "index": idx, "row": r, "reason": "invalid_time_or_quantity"})
            continue

        district_code = str(r.get("district_code"))
        solver_state_code = str(r.get("state_code"))
        mapped_state_code = district_to_state.get(district_code)
        state_code = str(mapped_state_code if mapped_state_code is not None else solver_state_code)
        resource_id = str(r.get("resource_id"))
        normalized_resource_id = resolve_resource_id(db, resource_id, strict=False)
        supply_level = str(r.get("supply_level") or "district").strip().lower()
        if supply_level == "national":
            origin_state_code = "NATIONAL"
        elif supply_level == "state":
            origin_state_code = solver_state_code
        else:
            origin_state_code = state_code

        if supply_level == "national":
            allocation_source_scope = "national"
            allocation_source_code = "NATIONAL"
        elif supply_level == "state":
            if str(origin_state_code) != str(state_code):
                allocation_source_scope = "neighbor_state"
            else:
                allocation_source_scope = "state"
            allocation_source_code = str(origin_state_code)
        else:
            allocation_source_scope = "district"
            allocation_source_code = str(district_code)

        if not district_code or district_code == "None":
            rejected_rows.append({"table": "allocation", "index": idx, "row": r, "reason": "missing_district_code"})
            continue
        if not state_code or state_code == "None":
            rejected_rows.append({"table": "allocation", "index": idx, "row": r, "reason": "missing_state_code"})
            continue
        if not normalized_resource_id or str(normalized_resource_id) == "None":
            rejected_rows.append({"table": "allocation", "index": idx, "row": r, "reason": "missing_resource_id"})
            continue

        slot_req = request_by_slot.get((district_code, str(normalized_resource_id), int(t)))
        src_request_id = (None if slot_req is None else int(slot_req.id))
        src_request_created_at = (None if slot_req is None else slot_req.created_at)
        src_batch_id = (None if slot_req is None else int(slot_req.run_id or solver_run_id))

        rows_to_insert.append({
            "solver_run_id": solver_run_id,
            "request_id": int(src_request_id or 0),
            "source_request_id": src_request_id,
            "source_request_created_at": src_request_created_at,
            "source_batch_id": src_batch_id,
            "supply_level": supply_level,
            "allocation_source_scope": allocation_source_scope,
            "allocation_source_code": allocation_source_code,
            "resource_id": str(normalized_resource_id),
            "district_code": district_code,
            "state_code": state_code,
            "origin_state": origin_state_code,
            "origin_state_code": origin_state_code,
            "origin_district_code": None,
            "time": t,
            "allocated_quantity": q,
            "implied_delay_hours": _compute_delay_hours(
                state_coords,
                (state_code if origin_state_code == "NATIONAL" else origin_state_code),
                state_code,
            ),
            "receipt_confirmed": False,
            "receipt_time": None,
            "is_unmet": False,
            "claimed_quantity": 0.0,
            "consumed_quantity": 0.0,
            "returned_quantity": 0.0,
            "status": "allocated",
        })

    # -----------------------
    # Unmet
    # -----------------------

    for idx, r in enumerate(unmet_rows):

        t = _safe_int(r.get("time"))
        q = _safe_float(r.get("unmet_quantity"))
        q = _integerize_positive_quantity(q)

        if t is None or q is None:
            rejected_rows.append({"table": "unmet", "index": idx, "row": r, "reason": "invalid_time_or_quantity"})
            continue

        district_code = str(r.get("district_code"))
        resource_id = str(r.get("resource_id"))
        normalized_resource_id = resolve_resource_id(db, resource_id, strict=False)
        state_code = district_to_state.get(district_code, "UNKNOWN")

        if not district_code or district_code == "None":
            rejected_rows.append({"table": "unmet", "index": idx, "row": r, "reason": "missing_district_code"})
            continue
        if not normalized_resource_id or str(normalized_resource_id) == "None":
            rejected_rows.append({"table": "unmet", "index": idx, "row": r, "reason": "missing_resource_id"})
            continue

        slot_req = request_by_slot.get((district_code, str(normalized_resource_id), int(t)))
        src_request_id = (None if slot_req is None else int(slot_req.id))
        src_request_created_at = (None if slot_req is None else slot_req.created_at)
        src_batch_id = (None if slot_req is None else int(slot_req.run_id or solver_run_id))

        rows_to_insert.append({
            "solver_run_id": solver_run_id,
            "request_id": int(src_request_id or 0),
            "source_request_id": src_request_id,
            "source_request_created_at": src_request_created_at,
            "source_batch_id": src_batch_id,
            "supply_level": "unmet",
            "allocation_source_scope": "unmet",
            "allocation_source_code": str(state_code),
            "resource_id": str(normalized_resource_id),
            "district_code": district_code,
            "state_code": state_code,
            "origin_state": state_code,
            "origin_state_code": state_code,
            "origin_district_code": None,
            "time": t,
            "allocated_quantity": q,
            "implied_delay_hours": 0.0,
            "receipt_confirmed": False,
            "receipt_time": None,
            "is_unmet": True,
            "claimed_quantity": 0.0,
            "consumed_quantity": 0.0,
            "returned_quantity": 0.0,
            "status": "unmet",
        })

    # Enforce time-index policy after parsing and before accounting/reconciliation.
    rows_to_insert = _apply_time_index_allocation_policy(
        rows_to_insert=rows_to_insert,
        request_total_by_slot=request_total_by_slot,
        request_by_slot=request_by_slot,
        district_to_state=district_to_state,
        state_coords=state_coords,
        district_resource_capacity=district_resource_capacity,
        state_resource_capacity=state_resource_capacity,
        interstate_resource_capacity=interstate_resource_capacity,
        national_resource_capacity=national_resource_capacity,
        solver_run_id=int(solver_run_id),
    )

    final_demand_rows = db.query(
        FinalDemand.district_code,
        FinalDemand.resource_id,
        FinalDemand.time,
        FinalDemand.demand_quantity,
    ).filter(FinalDemand.solver_run_id == int(solver_run_id)).all()

    final_demand_map = {
        (str(r.district_code), str(r.resource_id), int(r.time)): float(r.demand_quantity or 0.0)
        for r in final_demand_rows
    }

    slot_totals: dict[tuple[str, str, int], float] = {}
    for row in rows_to_insert:
        key = (str(row["district_code"]), str(row["resource_id"]), int(row["time"]))
        slot_totals[key] = slot_totals.get(key, 0.0) + float(row.get("allocated_quantity", 0.0) or 0.0)

    mismatched_slots = set()
    if final_demand_map:
        mismatched_slots = {
            key
            for key, observed_total in slot_totals.items()
            if abs(float(observed_total) - float(final_demand_map.get(key, 0.0))) > 1e-6
        }

    if mismatched_slots:
        slot_to_indices: dict[tuple[str, str, int], list[int]] = {}
        for idx, row in enumerate(rows_to_insert):
            key = (str(row["district_code"]), str(row["resource_id"]), int(row["time"]))
            slot_to_indices.setdefault(key, []).append(idx)

        adjusted_slots = set()
        for key in list(mismatched_slots):
            observed = float(slot_totals.get(key, 0.0))
            target = float(final_demand_map.get(key, 0.0))
            drift = observed - target
            tolerance = max(5.0, abs(target) * 0.001)

            if abs(drift) <= tolerance:
                candidate_indices = [i for i in slot_to_indices.get(key, []) if not bool(rows_to_insert[i].get("is_unmet"))]
                if not candidate_indices:
                    candidate_indices = list(slot_to_indices.get(key, []))
                if candidate_indices:
                    pivot_idx = max(candidate_indices, key=lambda i: float(rows_to_insert[i].get("allocated_quantity") or 0.0))
                    pivot_qty = float(rows_to_insert[pivot_idx].get("allocated_quantity") or 0.0)
                    new_qty = max(0.0, pivot_qty - drift)
                    rows_to_insert[pivot_idx]["allocated_quantity"] = float(new_qty)
                    slot_totals[key] = observed - pivot_qty + new_qty
                    adjusted_slots.add(key)

        if adjusted_slots:
            mismatched_slots = {
                key
                for key in mismatched_slots
                if abs(float(slot_totals.get(key, 0.0)) - float(final_demand_map.get(key, 0.0))) > 1e-6
            }

        if mismatched_slots:
            kept_rows = []
            fallback_unmet_rows = []
            for row in rows_to_insert:
                key = (str(row["district_code"]), str(row["resource_id"]), int(row["time"]))
                if key in mismatched_slots:
                    rejected_rows.append({
                        "table": "allocation_or_unmet",
                        "row": row,
                        "reason": "slot_total_mismatch_with_final_demand_fallback_to_unmet",
                        "observed_slot_total": slot_totals.get(key, 0.0),
                        "final_demand_total": final_demand_map.get(key, 0.0),
                    })
                    continue
                kept_rows.append(row)

            for key in mismatched_slots:
                district_code, resource_id, slot_time = key
                target = float(final_demand_map.get(key, 0.0))
                if target <= 0.0:
                    continue
                state_code = str(district_to_state.get(str(district_code), "UNKNOWN"))
                slot_req = request_by_slot.get((str(district_code), str(resource_id), int(slot_time)))
                src_request_id = (None if slot_req is None else int(slot_req.id))
                src_request_created_at = (None if slot_req is None else slot_req.created_at)
                src_batch_id = (None if slot_req is None else int(slot_req.run_id or solver_run_id))

                fallback_unmet_rows.append({
                    "solver_run_id": solver_run_id,
                    "request_id": int(src_request_id or 0),
                    "source_request_id": src_request_id,
                    "source_request_created_at": src_request_created_at,
                    "source_batch_id": src_batch_id,
                    "supply_level": "unmet",
                    "allocation_source_scope": "unmet",
                    "allocation_source_code": state_code,
                    "resource_id": str(resource_id),
                    "district_code": str(district_code),
                    "state_code": state_code,
                    "origin_state": state_code,
                    "origin_state_code": state_code,
                    "origin_district_code": None,
                    "time": int(slot_time),
                    "allocated_quantity": float(target),
                    "implied_delay_hours": 0.0,
                    "receipt_confirmed": False,
                    "receipt_time": None,
                    "is_unmet": True,
                    "claimed_quantity": 0.0,
                    "consumed_quantity": 0.0,
                    "returned_quantity": 0.0,
                    "status": "unmet",
                })

            rows_to_insert = kept_rows + fallback_unmet_rows

    # -----------------------
    # Inventory snapshots
    # -----------------------

    for idx, r in enumerate(inventory_rows):
        t = _safe_int(r.get("time"))
        q = _safe_float(r.get("quantity"))
        q = _integerize_positive_quantity(q)
        district_code = str(r.get("district_code"))
        resource_id = str(r.get("resource_id"))
        normalized_resource_id = resolve_resource_id(db, resource_id, strict=False)

        if t is None or q is None:
            rejected_rows.append({"table": "inventory_snapshot", "index": idx, "row": r, "reason": "invalid_time_or_quantity"})
            continue
        if not district_code or district_code == "None":
            rejected_rows.append({"table": "inventory_snapshot", "index": idx, "row": r, "reason": "missing_district_code"})
            continue
        if not normalized_resource_id or str(normalized_resource_id) == "None":
            rejected_rows.append({"table": "inventory_snapshot", "index": idx, "row": r, "reason": "missing_resource_id"})
            continue

        inventory_to_insert.append({
            "solver_run_id": solver_run_id,
            "district_code": district_code,
            "resource_id": str(normalized_resource_id),
            "time": t,
            "quantity": max(0.0, q),
        })

    if not inventory_to_insert:
        # Fallback: keep inventory snapshots non-empty for stock observability when solver omits inventory_t.csv.
        grouped: dict[tuple[str, str], float] = {}
        for row in rows_to_insert:
            if bool(row.get("is_unmet")):
                continue
            if str(row.get("supply_level") or "district").lower() != "district":
                continue
            key = (str(row.get("district_code")), str(row.get("resource_id")))
            grouped[key] = grouped.get(key, 0.0) + float(row.get("allocated_quantity") or 0.0)

        for (district_code, resource_id), allocated in grouped.items():
            inventory_to_insert.append({
                "solver_run_id": solver_run_id,
                "district_code": str(district_code),
                "resource_id": str(resource_id),
                "time": 0,
                "quantity": max(0.0, float(allocated)),
            })

    # -----------------------
    # Shipment plan
    # -----------------------
    # Build shipments from effective non-district allocations after policy enforcement.
    shipment_to_insert = []
    for row in rows_to_insert:
        if bool(row.get("is_unmet")):
            continue
        level = str(row.get("supply_level") or "district").lower()
        if level == "district":
            continue
        from_district = "NATIONAL" if level == "national" else f"STATE::{row.get('origin_state_code') or row.get('state_code') or 'UNKNOWN'}"
        shipment_to_insert.append({
            "solver_run_id": int(solver_run_id),
            "from_district": from_district,
            "to_district": str(row.get("district_code")),
            "resource_id": str(row.get("resource_id")),
            "time": int(row.get("time")),
            "quantity": max(0.0, float(row.get("allocated_quantity") or 0.0)),
            "status": "planned",
        })

    try:
        clear_allocations_for_run(db, solver_run_id, auto_commit=False)
        create_allocations_bulk(db, rows_to_insert, auto_commit=False)
        record_solver_allocation_debits(db, solver_run_id=int(solver_run_id), allocation_rows=rows_to_insert)

        db.query(InventorySnapshot).filter(InventorySnapshot.solver_run_id == solver_run_id).delete()
        db.query(ShipmentPlan).filter(ShipmentPlan.solver_run_id == solver_run_id).delete()

        if inventory_to_insert:
            db.bulk_save_objects([InventorySnapshot(**row) for row in inventory_to_insert])

        if shipment_to_insert:
            db.bulk_save_objects([ShipmentPlan(**row) for row in shipment_to_insert])

        reconcile_final_demands_with_allocations(db, solver_run_id)
        reconcile_requests_from_solver_run(db, solver_run_id)
        persist_solver_run_snapshot(db, solver_run_id=int(solver_run_id))
        db.commit()
    except Exception:
        db.rollback()
        raise

    if rejected_rows:
        logs_dir = Path(__file__).resolve().parents[3] / "core_engine" / "phase4" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        out_file = logs_dir / f"ingest_rejected_rows_run_{solver_run_id}_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
        out_file.write_text(json.dumps(rejected_rows, indent=2, default=str), encoding="utf-8")

    print(
        f"Ingested {len(alloc_rows)} allocations and "
        f"{len(unmet_rows)} unmet rows, "
        f"{len(inventory_to_insert)} inventory snapshots and "
        f"{len(shipment_to_insert)} shipment rows"
    )
