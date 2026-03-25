from datetime import datetime
from types import SimpleNamespace

from app.engine_bridge.ingest import _apply_time_index_allocation_policy


def test_preserves_existing_district_share_when_capacity_snapshot_is_zero():
    solver_run_id = 999001
    district_code = "603"
    state_code = "33"
    resource_id = "R28"
    slot_time = 0

    rows_to_insert = [
        {
            "solver_run_id": solver_run_id,
            "request_id": 1,
            "source_request_id": 1,
            "source_request_created_at": datetime.utcnow(),
            "source_batch_id": solver_run_id,
            "supply_level": "district",
            "allocation_source_scope": "district",
            "allocation_source_code": district_code,
            "resource_id": resource_id,
            "district_code": district_code,
            "state_code": state_code,
            "origin_state": state_code,
            "origin_state_code": state_code,
            "origin_district_code": district_code,
            "time": slot_time,
            "allocated_quantity": 50.0,
            "implied_delay_hours": 0.0,
            "receipt_confirmed": False,
            "receipt_time": None,
            "is_unmet": False,
            "claimed_quantity": 0.0,
            "consumed_quantity": 0.0,
            "returned_quantity": 0.0,
            "status": "allocated",
        },
        {
            "solver_run_id": solver_run_id,
            "request_id": 1,
            "source_request_id": 1,
            "source_request_created_at": datetime.utcnow(),
            "source_batch_id": solver_run_id,
            "supply_level": "state",
            "allocation_source_scope": "state",
            "allocation_source_code": state_code,
            "resource_id": resource_id,
            "district_code": district_code,
            "state_code": state_code,
            "origin_state": state_code,
            "origin_state_code": state_code,
            "origin_district_code": None,
            "time": slot_time,
            "allocated_quantity": 50.0,
            "implied_delay_hours": 0.0,
            "receipt_confirmed": False,
            "receipt_time": None,
            "is_unmet": False,
            "claimed_quantity": 0.0,
            "consumed_quantity": 0.0,
            "returned_quantity": 0.0,
            "status": "allocated",
        },
    ]

    request_total_by_slot = {(district_code, resource_id, slot_time): 100.0}
    request_by_slot = {
        (district_code, resource_id, slot_time): SimpleNamespace(
            id=1,
            run_id=solver_run_id,
            created_at=datetime.utcnow(),
            priority=5,
            urgency=5,
        )
    }

    adjusted = _apply_time_index_allocation_policy(
        rows_to_insert=rows_to_insert,
        request_total_by_slot=request_total_by_slot,
        request_by_slot=request_by_slot,
        district_to_state={district_code: state_code},
        state_coords={},
        district_resource_capacity={(district_code, resource_id): 0.0},
        state_resource_capacity={(state_code, resource_id): 100.0},
        interstate_resource_capacity={(state_code, resource_id): 0.0},
        national_resource_capacity={resource_id: 0.0},
        solver_run_id=solver_run_id,
    )

    district_qty = sum(
        float(r.get("allocated_quantity") or 0.0)
        for r in adjusted
        if not bool(r.get("is_unmet")) and str(r.get("allocation_source_scope")) == "district"
    )
    state_qty = sum(
        float(r.get("allocated_quantity") or 0.0)
        for r in adjusted
        if not bool(r.get("is_unmet")) and str(r.get("allocation_source_scope")) == "state"
    )

    assert district_qty > 0.0
    assert abs((district_qty + state_qty) - 100.0) < 1e-6


def test_nonzero_district_fallback_when_solver_rows_are_state_only():
    solver_run_id = 999002
    district_code = "603"
    state_code = "33"
    resource_id = "R28"
    slot_time = 0

    rows_to_insert = [
        {
            "solver_run_id": solver_run_id,
            "request_id": 1,
            "source_request_id": 1,
            "source_request_created_at": datetime.utcnow(),
            "source_batch_id": solver_run_id,
            "supply_level": "state",
            "allocation_source_scope": "state",
            "allocation_source_code": state_code,
            "resource_id": resource_id,
            "district_code": district_code,
            "state_code": state_code,
            "origin_state": state_code,
            "origin_state_code": state_code,
            "origin_district_code": None,
            "time": slot_time,
            "allocated_quantity": 100.0,
            "implied_delay_hours": 0.0,
            "receipt_confirmed": False,
            "receipt_time": None,
            "is_unmet": False,
            "claimed_quantity": 0.0,
            "consumed_quantity": 0.0,
            "returned_quantity": 0.0,
            "status": "allocated",
        },
    ]

    request_total_by_slot = {(district_code, resource_id, slot_time): 100.0}
    request_by_slot = {
        (district_code, resource_id, slot_time): SimpleNamespace(
            id=1,
            run_id=solver_run_id,
            created_at=datetime.utcnow(),
            priority=5,
            urgency=5,
        )
    }

    adjusted = _apply_time_index_allocation_policy(
        rows_to_insert=rows_to_insert,
        request_total_by_slot=request_total_by_slot,
        request_by_slot=request_by_slot,
        district_to_state={district_code: state_code},
        state_coords={},
        district_resource_capacity={(district_code, resource_id): 0.0},
        state_resource_capacity={(state_code, resource_id): 100.0},
        interstate_resource_capacity={(state_code, resource_id): 0.0},
        national_resource_capacity={resource_id: 0.0},
        solver_run_id=solver_run_id,
    )

    district_qty = sum(
        float(r.get("allocated_quantity") or 0.0)
        for r in adjusted
        if not bool(r.get("is_unmet")) and str(r.get("allocation_source_scope")) == "district"
    )
    total_fulfilled = sum(
        float(r.get("allocated_quantity") or 0.0)
        for r in adjusted
        if not bool(r.get("is_unmet"))
    )

    assert district_qty > 0.0
    assert abs(total_fulfilled - 100.0) < 1e-6
