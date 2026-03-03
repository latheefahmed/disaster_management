from sqlalchemy import func
from sqlalchemy.orm import Session
from pathlib import Path
from datetime import datetime
import json
from math import atan2, ceil, cos, radians, sin, sqrt

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
    return float(ceil(v))


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


def _request_status_from_totals(allocated: float, unmet: float) -> str:
    allocated_val = float(allocated or 0.0)
    unmet_val = float(unmet or 0.0)
    if allocated_val > 1e-9 and unmet_val <= 1e-9:
        return "allocated"
    if allocated_val > 1e-9 and unmet_val > 1e-9:
        return "partial"
    if allocated_val <= 1e-9 and unmet_val > 1e-9:
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
            status = _request_status_from_totals(allocated_val, unmet_val)

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
    request_by_slot: dict[tuple[str, str, int], ResourceRequest] = {}
    for req in run_request_rows:
        slot = (str(req.district_code), str(req.resource_id), int(req.time))
        if slot not in request_by_slot:
            request_by_slot[slot] = req

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

    # Ensure non-district allocations are visible as shipments even when solver shipment file is empty.
    if not shipment_rows:
        for row in rows_to_insert:
            supply_level = str(row.get("supply_level") or "district").lower()
            if supply_level == "district":
                continue
            from_district = "NATIONAL" if supply_level == "national" else f"STATE::{row.get('origin_state_code') or row.get('state_code') or 'UNKNOWN'}"
            shipment_to_insert.append({
                "solver_run_id": solver_run_id,
                "from_district": from_district,
                "to_district": str(row.get("district_code")),
                "resource_id": str(row.get("resource_id")),
                "time": int(row.get("time")),
                "quantity": max(0.0, float(row.get("allocated_quantity") or 0.0)),
                "status": "planned",
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
        kept_rows = []
        for row in rows_to_insert:
            key = (str(row["district_code"]), str(row["resource_id"]), int(row["time"]))
            if key in mismatched_slots:
                rejected_rows.append({
                    "table": "allocation_or_unmet",
                    "row": row,
                    "reason": "slot_total_mismatch_with_final_demand",
                    "observed_slot_total": slot_totals.get(key, 0.0),
                    "final_demand_total": final_demand_map.get(key, 0.0),
                })
                continue
            kept_rows.append(row)
        rows_to_insert = kept_rows

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

    for idx, r in enumerate(shipment_rows):
        t = _safe_int(r.get("time"))
        q = _safe_float(r.get("quantity"))
        q = _integerize_positive_quantity(q)
        from_district = str(r.get("from_district"))
        to_district = str(r.get("to_district"))
        resource_id = str(r.get("resource_id"))
        normalized_resource_id = resolve_resource_id(db, resource_id, strict=False)
        status = str(r.get("status") or "planned")

        if t is None or q is None:
            rejected_rows.append({"table": "shipment_plan", "index": idx, "row": r, "reason": "invalid_time_or_quantity"})
            continue
        if not from_district or from_district == "None":
            rejected_rows.append({"table": "shipment_plan", "index": idx, "row": r, "reason": "missing_from_district"})
            continue
        if not to_district or to_district == "None":
            rejected_rows.append({"table": "shipment_plan", "index": idx, "row": r, "reason": "missing_to_district"})
            continue
        if not normalized_resource_id or str(normalized_resource_id) == "None":
            rejected_rows.append({"table": "shipment_plan", "index": idx, "row": r, "reason": "missing_resource_id"})
            continue

        shipment_to_insert.append({
            "solver_run_id": solver_run_id,
            "from_district": from_district,
            "to_district": to_district,
            "resource_id": str(normalized_resource_id),
            "time": t,
            "quantity": max(0.0, q),
            "status": status,
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
        out_file.write_text(json.dumps(rejected_rows, indent=2), encoding="utf-8")

    print(
        f"Ingested {len(alloc_rows)} allocations and "
        f"{len(unmet_rows)} unmet rows, "
        f"{len(inventory_to_insert)} inventory snapshots and "
        f"{len(shipment_to_insert)} shipment rows"
    )
