import json
from datetime import datetime, UTC
from pathlib import Path

from sqlalchemy import func

from app.database import SessionLocal
from app.models.solver_run import SolverRun
from app.models.district import District
from app.models.allocation import Allocation
from app.models.request import ResourceRequest
from app.models.claim import Claim
from app.models.return_ import Return
from app.services.action_service import create_claim, create_return
from app.services.request_service import (
    get_district_requests_view,
    get_requests_for_state,
    get_state_allocation_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = REPO_ROOT / "core_engine/phase4/scenarios/generated/validation_matrix/lifecycle_visibility_snapshot.json"


def _fail(msg: str) -> None:
    raise RuntimeError(msg)


def _as_float(value) -> float:
    return float(value or 0.0)


def main() -> None:
    db = SessionLocal()
    try:
        run = (
            db.query(SolverRun)
            .filter(SolverRun.mode == "live")
            .order_by(SolverRun.id.desc())
            .first()
        )
        if not run:
            _fail("No live solver run found")

        seed_slot = (
            db.query(Allocation)
            .filter(Allocation.solver_run_id == run.id, Allocation.is_unmet == False)
            .order_by(Allocation.id.asc())
            .first()
        )
        district_code = str(seed_slot.district_code) if seed_slot else None
        state_code = str(seed_slot.state_code) if seed_slot and seed_slot.state_code else None

        if not district_code or not state_code:
            district = db.query(District).order_by(District.district_code.asc()).first()
            if not district:
                _fail("No district available for lifecycle check")
            district_code = str(district.district_code)
            state_code = str(district.state_code)

        resource_id = f"CERT_R_{int(run.id)}"
        base_time = 9100
        while True:
            slot_allocated = base_time + 1
            slot_partial = base_time + 2
            slot_unmet = base_time + 3
            slot_pending = base_time + 4
            slot_escalated = base_time + 5

            existing = (
                db.query(Allocation)
                .filter(
                    Allocation.solver_run_id == run.id,
                    Allocation.district_code == district_code,
                    Allocation.resource_id == resource_id,
                    Allocation.time.in_([slot_allocated, slot_partial, slot_unmet, slot_pending, slot_escalated]),
                )
                .count()
            )
            if existing == 0:
                break
            base_time += 10

        probe_request_ids: list[int] = []

        # Inject deterministic slot records for lifecycle checks.
        db.add_all(
            [
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    supply_level="district",
                    resource_id=resource_id,
                    district_code=district_code,
                    state_code=state_code,
                    origin_state=state_code,
                    origin_state_code=state_code,
                    origin_district_code=district_code,
                    time=slot_allocated,
                    allocated_quantity=8.0,
                    is_unmet=False,
                    status="allocated",
                ),
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    supply_level="district",
                    resource_id=resource_id,
                    district_code=district_code,
                    state_code=state_code,
                    origin_state=state_code,
                    origin_state_code=state_code,
                    origin_district_code=district_code,
                    time=slot_partial,
                    allocated_quantity=5.0,
                    is_unmet=False,
                    status="allocated",
                ),
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    supply_level="unmet",
                    resource_id=resource_id,
                    district_code=district_code,
                    state_code=state_code,
                    origin_state=state_code,
                    origin_state_code=state_code,
                    origin_district_code=district_code,
                    time=slot_unmet,
                    allocated_quantity=7.0,
                    is_unmet=True,
                    status="unmet",
                ),
            ]
        )

        req_alloc = ResourceRequest(
            district_code=district_code,
            state_code=state_code,
            resource_id=resource_id,
            time=slot_allocated,
            quantity=8.0,
            priority=2,
            urgency=3,
            confidence=1.0,
            source="lifecycle_probe",
            status="pending",
            included_in_run=1,
            queued=0,
        )
        req_partial = ResourceRequest(
            district_code=district_code,
            state_code=state_code,
            resource_id=resource_id,
            time=slot_partial,
            quantity=10.0,
            priority=2,
            urgency=2,
            confidence=1.0,
            source="lifecycle_probe",
            status="pending",
            included_in_run=1,
            queued=0,
        )
        req_unmet = ResourceRequest(
            district_code=district_code,
            state_code=state_code,
            resource_id=resource_id,
            time=slot_unmet,
            quantity=7.0,
            priority=1,
            urgency=2,
            confidence=1.0,
            source="lifecycle_probe",
            status="pending",
            included_in_run=1,
            queued=0,
        )
        req_pending = ResourceRequest(
            district_code=district_code,
            state_code=state_code,
            resource_id=resource_id,
            time=slot_pending,
            quantity=4.0,
            priority=1,
            urgency=1,
            confidence=1.0,
            source="lifecycle_probe",
            status="pending",
            included_in_run=0,
            queued=1,
        )
        req_escalated = ResourceRequest(
            district_code=district_code,
            state_code=state_code,
            resource_id=resource_id,
            time=slot_escalated,
            quantity=3.0,
            priority=1,
            urgency=1,
            confidence=1.0,
            source="lifecycle_probe",
            status="escalated_national",
            included_in_run=1,
            queued=0,
        )
        db.add_all([req_alloc, req_partial, req_unmet, req_pending, req_escalated])
        db.commit()
        probe_request_ids = [
            int(req_alloc.id),
            int(req_partial.id),
            int(req_unmet.id),
            int(req_pending.id),
            int(req_escalated.id),
        ]

        # Trigger request status refresh and capture district/state views.
        district_view = get_district_requests_view(db, district_code=district_code)
        state_view = get_requests_for_state(db, state_code=state_code)

        district_by_id = {int(r["id"]): str(r["status"]) for r in district_view if int(r["id"]) in {
            int(req_alloc.id),
            int(req_partial.id),
            int(req_unmet.id),
            int(req_pending.id),
            int(req_escalated.id),
        }}
        state_by_id = {int(r.id): str(r.status) for r in state_view if int(r.id) in district_by_id}

        expected_statuses = {
            int(req_alloc.id): "allocated",
            int(req_partial.id): "partial",
            int(req_unmet.id): "unmet",
            int(req_pending.id): "pending",
            int(req_escalated.id): "escalated_national",
        }

        for rid, expected in expected_statuses.items():
            actual_district = district_by_id.get(rid)
            actual_state = state_by_id.get(rid)
            if actual_district != expected:
                _fail(f"District status mismatch for request {rid}: expected {expected}, got {actual_district}")
            if actual_state != expected:
                _fail(f"State status mismatch for request {rid}: expected {expected}, got {actual_state}")

        # Allocation slot lifecycle transitions: allocated -> claimed -> partially_returned -> closed.
        slot_row = (
            db.query(Allocation)
            .filter(
                Allocation.solver_run_id == run.id,
                Allocation.district_code == district_code,
                Allocation.resource_id == resource_id,
                Allocation.time == slot_allocated,
                Allocation.is_unmet == False,
            )
            .first()
        )
        if not slot_row:
            _fail("Unable to load injected allocation slot")

        before_status = str(slot_row.status)
        _, after_claim = create_claim(
            db=db,
            district_code=district_code,
            resource_id=resource_id,
            time=slot_allocated,
            quantity=8,
            claimed_by="lifecycle_probe",
        )
        _, after_return_partial = create_return(
            db=db,
            district_code=district_code,
            resource_id=resource_id,
            state_code=state_code,
            time=slot_allocated,
            quantity=3,
            reason="lifecycle_probe_partial",
        )
        _, after_return_full = create_return(
            db=db,
            district_code=district_code,
            resource_id=resource_id,
            state_code=state_code,
            time=slot_allocated,
            quantity=5,
            reason="lifecycle_probe_full",
        )

        lifecycle_sequence = [
            before_status,
            str(after_claim["status"]),
            str(after_return_partial["status"]),
            str(after_return_full["status"]),
        ]
        if lifecycle_sequence != ["allocated", "claimed", "partially_returned", "closed"]:
            _fail(f"Unexpected slot lifecycle sequence: {lifecycle_sequence}")

        # State summary parity with district-level allocation slot totals.
        state_summary = get_state_allocation_summary(db, state_code)
        summary_row = None
        for row in state_summary.get("rows", []):
            if (
                str(row.get("district_code")) == district_code
                and str(row.get("resource_id")) == resource_id
                and int(row.get("time")) == slot_allocated
            ):
                summary_row = row
                break

        if not summary_row:
            _fail("State allocation summary missing injected district slot")

        district_slot_alloc = (
            db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0))
            .filter(
                Allocation.solver_run_id == run.id,
                Allocation.district_code == district_code,
                Allocation.resource_id == resource_id,
                Allocation.time == slot_allocated,
                Allocation.is_unmet == False,
            )
            .scalar()
        )

        state_summary_alloc = _as_float(summary_row.get("allocated_quantity"))
        if abs(_as_float(district_slot_alloc) - state_summary_alloc) > 1e-6:
            _fail(
                f"State summary allocated mismatch for slot: district={district_slot_alloc}, state_summary={state_summary_alloc}"
            )

        out = {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "solver_run_id": int(run.id),
            "probe": {
                "district_code": district_code,
                "state_code": state_code,
                "resource_id": resource_id,
                "time_slots": {
                    "allocated": slot_allocated,
                    "partial": slot_partial,
                    "unmet": slot_unmet,
                    "pending": slot_pending,
                    "escalated": slot_escalated,
                },
            },
            "request_status_checks": {
                "expected": expected_statuses,
                "district_view": district_by_id,
                "state_view": state_by_id,
                "all_match": expected_statuses == district_by_id == state_by_id,
            },
            "allocation_slot_lifecycle": {
                "sequence": lifecycle_sequence,
                "expected": ["allocated", "claimed", "partially_returned", "closed"],
                "passed": lifecycle_sequence == ["allocated", "claimed", "partially_returned", "closed"],
            },
            "state_parity": {
                "district_slot_allocated_sum": _as_float(district_slot_alloc),
                "state_summary_allocated_quantity": state_summary_alloc,
                "equal": abs(_as_float(district_slot_alloc) - state_summary_alloc) <= 1e-6,
                "state_summary_row": summary_row,
                "state_lineage_all_consistent": bool((state_summary.get("lineage") or {}).get("all_consistent", False)),
            },
            "ui_surface_map": {
                "district_request_log": {
                    "surface": "district request status log",
                    "endpoint": "/district/requests",
                    "statuses": ["pending", "allocated", "partial", "unmet", "escalated_national"],
                },
                "state_requests_table": {
                    "surface": "state requests and rebalancing table",
                    "endpoint": "/state/requests",
                    "statuses": ["pending", "allocated", "partial", "unmet", "escalated_national"],
                },
                "district_allocation_lifecycle": {
                    "surface": "district claim/consume/return cards",
                    "endpoint": "/district/allocations + /district/claims + /district/returns",
                    "statuses": ["allocated", "claimed", "partially_consumed", "partially_returned", "closed", "empty"],
                },
                "state_allocations_detail": {
                    "surface": "state allocations summary/detail by district",
                    "endpoint": "/state/allocations/summary",
                    "district_dimension_present": True,
                },
                "terminology_note": {
                    "ready_maps_to": "pending",
                    "returned_maps_to": "partially_returned/closed (slot lifecycle)",
                    "dropped_status_present": False,
                    "dropped_rendered_as": "closed or zero/empty slot depending context",
                },
            },
        }

        ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
        print(f"[ok] lifecycle visibility artifact written: {ARTIFACT_PATH}")

        db.query(Claim).filter(
            Claim.solver_run_id == int(run.id),
            Claim.district_code == district_code,
            Claim.resource_id == resource_id,
            Claim.time.in_([slot_allocated, slot_partial, slot_unmet, slot_pending, slot_escalated]),
        ).delete(synchronize_session=False)

        db.query(Return).filter(
            Return.solver_run_id == int(run.id),
            Return.district_code == district_code,
            Return.resource_id == resource_id,
            Return.time.in_([slot_allocated, slot_partial, slot_unmet, slot_pending, slot_escalated]),
        ).delete(synchronize_session=False)

        db.query(ResourceRequest).filter(ResourceRequest.id.in_(probe_request_ids)).delete(synchronize_session=False)
        db.query(Allocation).filter(
            Allocation.solver_run_id == int(run.id),
            Allocation.district_code == district_code,
            Allocation.resource_id == resource_id,
            Allocation.time.in_([slot_allocated, slot_partial, slot_unmet, slot_pending, slot_escalated]),
        ).delete(synchronize_session=False)
        db.commit()

    finally:
        db.close()


if __name__ == "__main__":
    main()
