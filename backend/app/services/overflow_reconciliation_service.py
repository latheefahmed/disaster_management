from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.allocation import Allocation
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.services.action_service import create_claim, create_return
from app.services.stock_refill_service import create_stock_refill
from app.services.canonical_resources import can_return_resource, max_quantity_for


@dataclass
class OverflowReconcileOptions:
    keep_latest: int = 300
    chunk_size: int = 100
    only_district_code: str | None = None
    dry_run: bool = True
    reconcile_run_id: str = "system_overflow_reconciler"
    max_process: int | None = None


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _allocation_sort_query(db: Session, district_code: str | None = None):
    query = db.query(
        Allocation,
        ResourceRequest.created_at.label("request_created_at"),
    ).join(
        SolverRun,
        SolverRun.id == Allocation.solver_run_id,
    ).outerjoin(
        ResourceRequest,
        ResourceRequest.id == Allocation.request_id,
    ).filter(
        SolverRun.status == "completed",
        Allocation.is_unmet == False,
    )

    if district_code:
        query = query.filter(Allocation.district_code == str(district_code))

    query = query.order_by(
        Allocation.solver_run_id.desc(),
        func.coalesce(ResourceRequest.created_at, Allocation.created_at).desc(),
        ResourceRequest.id.desc(),
        Allocation.id.desc(),
    )
    return query


def _resolve_refill_target(allocation: Allocation) -> tuple[str, str | None, str | None]:
    source_scope = str(allocation.allocation_source_scope or allocation.supply_level or "district").strip().lower()
    source_code = str(allocation.allocation_source_code or "").strip()

    if source_scope in {"state", "neighbor_state"}:
        refill_state = source_code or str(allocation.origin_state_code or allocation.state_code or "")
        if refill_state and refill_state.upper() != "NATIONAL":
            return "state", None, str(refill_state)

    if source_scope == "national":
        return "national", None, None

    return "district", str(allocation.district_code), str(allocation.state_code or "")


def _remaining_unsettled_quantity(allocation: Allocation) -> float:
    allocated = _safe_float(allocation.allocated_quantity)
    consumed = _safe_float(allocation.consumed_quantity)
    returned = _safe_float(allocation.returned_quantity)
    remaining = allocated - consumed - returned
    return max(0.0, float(remaining))


def _mark_reconciled(
    db: Session,
    allocation_id: int,
    run_id: str,
    mode: str,
    quantity: float,
):
    refreshed = db.query(Allocation).filter(Allocation.id == int(allocation_id)).first()
    if refreshed is None:
        return
    refreshed.overflow_reconciled_at = datetime.utcnow()
    refreshed.overflow_reconcile_mode = str(mode)
    refreshed.overflow_reconcile_run_id = str(run_id)
    refreshed.overflow_reconciled_quantity = float(max(0.0, quantity))


def reconcile_overflow_allocations(db: Session, options: OverflowReconcileOptions) -> dict[str, Any]:
    rows = _allocation_sort_query(db, district_code=options.only_district_code).all()

    active_rows = rows[: max(0, int(options.keep_latest))]
    overflow_rows = rows[max(0, int(options.keep_latest)) :]

    active_ids = {int(row[0].id) for row in active_rows}

    summary: dict[str, Any] = {
        "keep_latest": int(options.keep_latest),
        "scope": ("all" if not options.only_district_code else f"district:{options.only_district_code}"),
        "dry_run": bool(options.dry_run),
        "active_count": len(active_ids),
        "overflow_candidates": len(overflow_rows),
        "processed": 0,
        "returned": 0,
        "refilled": 0,
        "skipped": 0,
        "failed": 0,
        "returned_quantity": 0.0,
        "refilled_quantity": 0.0,
        "errors": [],
        "max_process": (None if options.max_process is None else int(options.max_process)),
    }

    if not overflow_rows:
        return summary

    for start in range(0, len(overflow_rows), max(1, int(options.chunk_size))):
        chunk = overflow_rows[start : start + max(1, int(options.chunk_size))]
        for allocation, _request_created_at in chunk:
            if options.max_process is not None and int(summary["processed"]) >= int(options.max_process):
                summary["stopped_early"] = True
                return summary

            if int(allocation.id) in active_ids:
                continue

            if allocation.overflow_reconciled_at is not None:
                summary["skipped"] += 1
                continue

            remaining = _remaining_unsettled_quantity(allocation)
            if remaining <= 1e-9:
                if not options.dry_run:
                    allocation.overflow_reconciled_at = datetime.utcnow()
                    allocation.overflow_reconcile_mode = "skipped_zero_remaining"
                    allocation.overflow_reconcile_run_id = str(options.reconcile_run_id)
                    allocation.overflow_reconciled_quantity = 0.0
                summary["skipped"] += 1
                continue

            try:
                resource_id = str(allocation.resource_id)
                district_code = str(allocation.district_code)
                state_code = str(allocation.state_code or "")
                solver_run_id = int(allocation.solver_run_id)
                time_slot = int(allocation.time)

                if can_return_resource(resource_id):
                    already_claimed_remaining = max(
                        0.0,
                        _safe_float(allocation.claimed_quantity) - _safe_float(allocation.consumed_quantity) - _safe_float(allocation.returned_quantity),
                    )
                    claim_needed = max(0.0, remaining - already_claimed_remaining)
                    max_additional_claim = max(
                        0.0,
                        _safe_float(allocation.allocated_quantity) - _safe_float(allocation.claimed_quantity),
                    )
                    claim_needed = min(claim_needed, max_additional_claim)
                    max_step_qty = max(1.0, float(max_quantity_for(resource_id)))

                    if not options.dry_run:
                        claim_left = float(claim_needed)
                        while claim_left > 1e-9:
                            claim_qty = min(claim_left, max_step_qty)
                            try:
                                create_claim(
                                    db=db,
                                    district_code=district_code,
                                    resource_id=resource_id,
                                    time=time_slot,
                                    quantity=float(claim_qty),
                                    claimed_by="system_overflow_reconciler",
                                    solver_run_id=solver_run_id,
                                )
                            except Exception as claim_exc:
                                msg = str(claim_exc)
                                if "allocation status 'RETURNED'" in msg:
                                    _mark_reconciled(
                                        db=db,
                                        allocation_id=int(allocation.id),
                                        run_id=str(options.reconcile_run_id),
                                        mode="skipped_returned_status",
                                        quantity=0.0,
                                    )
                                    summary["skipped"] += 1
                                    claim_left = 0.0
                                    remaining = 0.0
                                    break
                                if "Claim quantity exceeds allocated quantity" in msg:
                                    _mark_reconciled(
                                        db=db,
                                        allocation_id=int(allocation.id),
                                        run_id=str(options.reconcile_run_id),
                                        mode="skipped_claim_cap",
                                        quantity=0.0,
                                    )
                                    summary["skipped"] += 1
                                    claim_left = 0.0
                                    remaining = 0.0
                                    break
                                raise
                            claim_left -= float(claim_qty)

                        return_left = float(remaining)
                        while return_left > 1e-9:
                            return_qty = min(return_left, max_step_qty)
                            try:
                                create_return(
                                    db=db,
                                    district_code=district_code,
                                    state_code=state_code,
                                    resource_id=resource_id,
                                    time=time_slot,
                                    quantity=float(return_qty),
                                    reason="overflow_window_reconciliation",
                                    solver_run_id=solver_run_id,
                                    allocation_source_scope=allocation.allocation_source_scope,
                                    allocation_source_code=allocation.allocation_source_code,
                                )
                            except Exception as return_exc:
                                return_msg = str(return_exc)
                                if "allocation status 'RETURNED'" in return_msg:
                                    _mark_reconciled(
                                        db=db,
                                        allocation_id=int(allocation.id),
                                        run_id=str(options.reconcile_run_id),
                                        mode="skipped_returned_status",
                                        quantity=0.0,
                                    )
                                    summary["skipped"] += 1
                                    return_left = 0.0
                                    remaining = 0.0
                                    break
                                if "Return quantity exceeds claimed remaining quantity" in return_msg:
                                    _mark_reconciled(
                                        db=db,
                                        allocation_id=int(allocation.id),
                                        run_id=str(options.reconcile_run_id),
                                        mode="skipped_return_cap",
                                        quantity=0.0,
                                    )
                                    summary["skipped"] += 1
                                    return_left = 0.0
                                    remaining = 0.0
                                    break
                                raise
                            return_left -= float(return_qty)

                        if remaining > 1e-9:
                            _mark_reconciled(
                                db=db,
                                allocation_id=int(allocation.id),
                                run_id=str(options.reconcile_run_id),
                                mode="returned",
                                quantity=float(remaining),
                            )

                    if remaining > 1e-9:
                        summary["returned"] += 1
                        summary["returned_quantity"] += float(remaining)
                else:
                    refill_scope, refill_district, refill_state = _resolve_refill_target(allocation)

                    if not options.dry_run:
                        create_stock_refill(
                            db=db,
                            scope=refill_scope,
                            resource_id=resource_id,
                            quantity=float(remaining),
                            actor_role="system",
                            actor_id="system_overflow_reconciler",
                            district_code=refill_district,
                            state_code=refill_state,
                            note=f"overflow_window_reconciliation:{options.reconcile_run_id}",
                        )
                        _mark_reconciled(
                            db=db,
                            allocation_id=int(allocation.id),
                            run_id=str(options.reconcile_run_id),
                            mode="refilled_non_returnable",
                            quantity=float(remaining),
                        )

                    summary["refilled"] += 1
                    summary["refilled_quantity"] += float(remaining)

                summary["processed"] += 1
            except Exception as exc:
                db.rollback()
                summary["failed"] += 1
                summary["errors"].append(
                    {
                        "allocation_id": int(allocation.id),
                        "solver_run_id": int(allocation.solver_run_id),
                        "district_code": str(allocation.district_code),
                        "resource_id": str(allocation.resource_id),
                        "time": int(allocation.time),
                        "error": str(exc),
                    }
                )

        if not options.dry_run:
            db.commit()

    return summary
