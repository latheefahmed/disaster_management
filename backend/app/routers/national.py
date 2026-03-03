from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.services.request_service import (
    get_all_requests,
    get_national_allocations,
    get_national_allocations_cursor,
    get_national_allocations_delta,
    get_national_unmet,
    get_national_allocation_summary,
    get_national_run_history,
    get_national_escalations,
    resolve_national_escalation,
)
from app.services.action_service import (
    get_global_pool_balance,
    get_state_pool_balance,
    allocate_from_pool_as_national,
    list_global_pool_transactions,
)
from app.schemas.state import NationalPoolAllocateCreate
from app.schemas.stock_refill import StockRefillCreate
from app.schemas.kpi import KPIOut
from app.schemas.stock import StockRowOut
from app.services.kpi_service import compute_national_kpis, get_national_stock_rows
from app.services.stock_refill_service import create_stock_refill
from app.utils.security import get_token_payload, require_roles
from app.services.live_stream_service import stream_allocations_delta
from app.services.perf_observability import log_perf_event
import time

router = APIRouter()
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200


def _pagination(page: int, page_size: int) -> tuple[int, int]:
    if int(page) < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if int(page_size) < 1 or int(page_size) > MAX_PAGE_SIZE:
        raise HTTPException(status_code=400, detail=f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    limit = int(page_size)
    offset = (int(page) - 1) * limit
    return limit, offset


def _require_stream_role(token: str, roles: list[str]):
    payload = get_token_payload(str(token or "").strip())
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return require_roles(roles)(payload)


@router.get("/me")
def national_me(user=Depends(require_role(["national"]))):
    return {
        "message": "National access confirmed",
        "user": user
    }


@router.get("/kpis", response_model=KPIOut)
def national_kpis(
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    return compute_national_kpis(db)


@router.get("/stock", response_model=list[StockRowOut])
def national_stock(
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    return get_national_stock_rows(db)


@router.get("/allocations/stock", response_model=list[StockRowOut])
def national_allocations_stock(
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    return get_national_stock_rows(db)


@router.post("/stock/refill")
def national_stock_refill(
    payload: StockRefillCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"])),
):
    try:
        row = create_stock_refill(
            db=db,
            scope="national",
            resource_id=payload.resource_id,
            quantity=float(payload.quantity),
            actor_role="national",
            actor_id="NATIONAL",
            note=payload.note,
        )
        return {"status": "ok", "refill_id": int(row.id)}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/requests")
def all_requests(
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    return get_all_requests(db)


@router.get("/allocations")
def national_allocations(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    limit, offset = _pagination(page, page_size)
    started = time.perf_counter() * 1000.0
    rows = get_national_allocations(db, limit=limit, offset=offset)
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/national/allocations",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
    )
    return rows


@router.get("/allocations/cursor")
def national_allocations_cursor(
    cursor_id: int | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    limit, _ = _pagination(1, page_size)
    return get_national_allocations_cursor(
        db,
        cursor_id=cursor_id,
        limit=limit,
    )


@router.get("/allocations/delta")
def national_allocations_delta(
    since_run_id: int = 0,
    since_allocation_id: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    limit, _ = _pagination(1, page_size)
    return get_national_allocations_delta(
        db,
        since_run_id=since_run_id,
        since_allocation_id=since_allocation_id,
        limit=limit,
    )


@router.get("/allocations/stream")
async def national_allocations_stream(
    token: str = Query(...),
    interval: float = 1.5,
    db: Session = Depends(get_db),
):
    _require_stream_role(token, ["national"])

    def _fetch(since_run_id: int, since_allocation_id: int):
        return get_national_allocations_delta(
            db,
            since_run_id=since_run_id,
            since_allocation_id=since_allocation_id,
            limit=300,
        )

    return StreamingResponse(
        stream_allocations_delta(
            role="national",
            role_code="NATIONAL",
            fetcher=_fetch,
            interval_seconds=interval,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/allocations/summary")
def national_allocations_summary(
    state_code: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    limit, offset = _pagination(page, page_size)
    started = time.perf_counter() * 1000.0
    payload = get_national_allocation_summary(db)
    if state_code:
        rows = [
            row for row in payload.get("rows", [])
            if str(row.get("state_code", "")) == str(state_code)
        ]
        payload["rows"] = rows
    payload["rows"] = list((payload or {}).get("rows") or [])[offset:offset + limit]
    total_rows = len((payload or {}).get("rows") or [])
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/national/allocations/summary",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=total_rows,
        rows_returned=total_rows,
        extra={"state_filter": state_code or ""},
    )
    return payload


@router.get("/run-history")
def national_run_history(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    limit, offset = _pagination(page, page_size)
    started = time.perf_counter() * 1000.0
    rows = get_national_run_history(db, limit=limit, offset=offset)
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/national/run-history",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
    )
    return rows


@router.get("/unmet")
def national_unmet(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    limit, offset = _pagination(page, page_size)
    return get_national_unmet(db, limit=limit, offset=offset)


@router.get("/escalations")
def national_escalations(
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    return get_national_escalations(db)


@router.post("/escalations/{request_id}/resolve")
def national_resolve_escalation(
    request_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    return resolve_national_escalation(
        db,
        request_id=request_id,
        decision=data.get("decision", "unmet"),
        note=data.get("note")
    )


@router.get("/pool")
def national_pool(
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    started = time.perf_counter() * 1000.0
    rows = get_global_pool_balance(db)
    total = float(sum(float(r["quantity"]) for r in rows))
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/national/pool",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
    )
    return {
        "total_quantity": total,
        "rows": rows,
    }


@router.get("/pool/transactions")
def national_pool_transactions(
    limit: int = 300,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    started = time.perf_counter() * 1000.0
    rows = list_global_pool_transactions(db, limit=limit)
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/national/pool/transactions",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
    )
    return rows


@router.get("/pool/{state_code}")
def national_pool_for_state(
    state_code: str,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    return get_state_pool_balance(db, state_code)


@router.post("/pool/allocate")
def national_pool_allocate(
    payload: NationalPoolAllocateCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role(["national"]))
):
    try:
        tx = allocate_from_pool_as_national(
            db=db,
            state_code=payload.state_code,
            resource_id=payload.resource_id,
            time=payload.time,
            quantity=float(payload.quantity),
            target_district=payload.target_district,
            note=payload.note,
        )
        return {"status": "ok", "transaction_id": tx.id}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
