from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.allocation import Allocation
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.services.canonical_resources import can_return_resource


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _remaining_unsettled_quantity(allocation: Allocation) -> float:
    allocated = _safe_float(allocation.allocated_quantity)
    consumed = _safe_float(allocation.consumed_quantity)
    returned = _safe_float(allocation.returned_quantity)
    return max(0.0, allocated - consumed - returned)


def _overflow_rows(db: Session, keep_latest: int, district_code: str | None = None):
    query = db.query(Allocation).join(
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

    rows = query.order_by(
        Allocation.solver_run_id.desc(),
        func.coalesce(ResourceRequest.created_at, Allocation.created_at).desc(),
        ResourceRequest.id.desc(),
        Allocation.id.desc(),
    ).all()

    return rows[max(0, int(keep_latest)) :]


def validate_overflow_reconciliation(
    db: Session,
    keep_latest: int = 300,
    district_code: str | None = None,
) -> dict[str, Any]:
    overflow_rows = _overflow_rows(db, keep_latest=keep_latest, district_code=district_code)

    unresolved = 0
    invalid_mode_for_returnable = 0
    invalid_mode_for_non_returnable = 0
    by_mode: dict[str, int] = {}

    allowed_returnable_modes = {
        "returned",
        "skipped_returned_status",
        "skipped_claim_cap",
        "skipped_return_cap",
        "skipped_zero_remaining",
    }
    allowed_non_returnable_modes = {
        "refilled_non_returnable",
        "skipped_zero_remaining",
    }

    for row in overflow_rows:
        mode = str(row.overflow_reconcile_mode or "")
        by_mode[mode] = int(by_mode.get(mode, 0)) + 1

        if row.overflow_reconciled_at is None and _remaining_unsettled_quantity(row) > 1e-9:
            unresolved += 1
            continue

        if row.overflow_reconciled_at is None:
            continue

        is_returnable = can_return_resource(str(row.resource_id))
        if is_returnable and mode not in allowed_returnable_modes:
            invalid_mode_for_returnable += 1
        if (not is_returnable) and mode not in allowed_non_returnable_modes:
            invalid_mode_for_non_returnable += 1

    issues: list[str] = []
    if unresolved > 0:
        issues.append(f"unresolved_overflow={unresolved}")
    if invalid_mode_for_returnable > 0:
        issues.append(f"invalid_mode_for_returnable={invalid_mode_for_returnable}")
    if invalid_mode_for_non_returnable > 0:
        issues.append(f"invalid_mode_for_non_returnable={invalid_mode_for_non_returnable}")

    return {
        "keep_latest": int(keep_latest),
        "scope": ("all" if district_code is None else f"district:{district_code}"),
        "overflow_candidates": len(overflow_rows),
        "unresolved_overflow": int(unresolved),
        "invalid_mode_for_returnable": int(invalid_mode_for_returnable),
        "invalid_mode_for_non_returnable": int(invalid_mode_for_non_returnable),
        "mode_counts": by_mode,
        "ok": len(issues) == 0,
        "issues": issues,
    }
