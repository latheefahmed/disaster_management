from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.models.allocation import Allocation

router = APIRouter()


def _allocation_rows_for_export(db: Session, run_id: int, user: dict, unmet_only: bool) -> list[Allocation]:
    role = str(user.get("role") or "")
    query = db.query(Allocation).filter(Allocation.solver_run_id == int(run_id), Allocation.is_unmet == bool(unmet_only))

    if role == "district":
        query = query.filter(Allocation.district_code == str(user.get("district_code") or ""))
    elif role == "state":
        query = query.filter(Allocation.state_code == str(user.get("state_code") or ""))
    elif role in {"national", "admin"}:
        pass
    else:
        raise HTTPException(status_code=403, detail="Unsupported role for export")

    return query.order_by(Allocation.created_at.desc(), Allocation.id.desc()).all()


def _csv_stream(rows: Iterable[Allocation], unmet_only: bool):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "solver_run_id",
        "request_id",
        "district_code",
        "state_code",
        "resource_id",
        "time",
        "quantity",
        "is_unmet",
        "supply_level",
        "allocation_source_scope",
        "allocation_source_code",
        "created_at",
    ])
    yield output.getvalue()
    output.seek(0)
    output.truncate(0)

    for row in rows:
        writer.writerow([
            int(row.id),
            int(row.solver_run_id),
            None if row.request_id is None else int(row.request_id),
            str(row.district_code),
            str(row.state_code),
            str(row.resource_id),
            int(row.time),
            float(row.allocated_quantity or 0.0),
            1 if bool(unmet_only) else 0,
            str(row.supply_level or ""),
            str(row.allocation_source_scope or ""),
            str(row.allocation_source_code or ""),
            "" if row.created_at is None else str(row.created_at),
        ])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)


@router.get("/allocations")
def export_allocations(
    run_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district", "state", "national", "admin"])),
):
    rows = _allocation_rows_for_export(db, int(run_id), user, unmet_only=False)
    filename = f"allocations_run_{int(run_id)}.csv"
    return StreamingResponse(
        _csv_stream(rows, unmet_only=False),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/unmet")
def export_unmet(
    run_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district", "state", "national", "admin"])),
):
    rows = _allocation_rows_for_export(db, int(run_id), user, unmet_only=True)
    filename = f"unmet_run_{int(run_id)}.csv"
    return StreamingResponse(
        _csv_stream(rows, unmet_only=True),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
