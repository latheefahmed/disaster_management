from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.services.request_service import (
    get_requests_for_state,
    get_state_allocations,
    get_state_allocations_cursor,
    get_state_allocations_delta,
    get_state_unmet,
    get_state_allocation_summary,
    get_state_run_history,
    get_state_escalation_candidates,
    escalate_request_to_national,
)
from app.services.action_service import (
    get_state_pool_balance,
    allocate_from_state_pool,
    list_state_pool_transactions,
)
from app.services.mutual_aid_service import (
    list_requests_for_state,
    list_market_requests_for_offering_state,
    create_mutual_aid_offer,
    respond_to_offer,
)
from app.services.agent_engine import list_recommendations, decide_recommendation
from app.models.agent_finding import AgentFinding
from app.models.district import District
from app.schemas.district import PoolAllocateCreate
from app.schemas.stock_refill import StockRefillCreate
from app.schemas.kpi import KPIOut
from app.schemas.stock import StockRowOut
from app.services.kpi_service import compute_state_kpis, get_state_stock_rows
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
def state_me(user=Depends(require_role(["state"]))):
    return {
        "message": "State access confirmed",
        "user": user
    }


@router.get("/kpis", response_model=KPIOut)
def state_kpis(
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    return compute_state_kpis(db, str(user["state_code"]))


@router.get("/stock", response_model=list[StockRowOut])
def state_stock(
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    return get_state_stock_rows(db, str(user["state_code"]))


@router.post("/stock/refill")
def state_stock_refill(
    payload: StockRefillCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"])),
):
    try:
        row = create_stock_refill(
            db=db,
            scope="state",
            resource_id=payload.resource_id,
            quantity=float(payload.quantity),
            actor_role="state",
            actor_id=str(user["state_code"]),
            state_code=str(user["state_code"]),
            note=payload.note,
        )
        return {"status": "ok", "refill_id": int(row.id)}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/requests")
def state_requests(
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    return get_requests_for_state(db, user["state_code"])


@router.get("/allocations")
def state_allocations(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    limit, offset = _pagination(page, page_size)
    started = time.perf_counter() * 1000.0
    rows = get_state_allocations(db, user["state_code"], limit=limit, offset=offset)
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/state/allocations",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
        extra={"state_code": str(user["state_code"])},
    )
    return rows


@router.get("/allocations/cursor")
def state_allocations_cursor(
    cursor_id: int | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    limit, _ = _pagination(1, page_size)
    return get_state_allocations_cursor(
        db,
        user["state_code"],
        cursor_id=cursor_id,
        limit=limit,
    )


@router.get("/allocations/delta")
def state_allocations_delta(
    since_run_id: int = 0,
    since_allocation_id: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    limit, _ = _pagination(1, page_size)
    return get_state_allocations_delta(
        db,
        user["state_code"],
        since_run_id=since_run_id,
        since_allocation_id=since_allocation_id,
        limit=limit,
    )


@router.get("/allocations/stream")
async def state_allocations_stream(
    token: str = Query(...),
    interval: float = 1.5,
    db: Session = Depends(get_db),
):
    user = _require_stream_role(token, ["state"])
    state_code = str(user.get("state_code") or "")

    def _fetch(since_run_id: int, since_allocation_id: int):
        return get_state_allocations_delta(
            db,
            state_code,
            since_run_id=since_run_id,
            since_allocation_id=since_allocation_id,
            limit=300,
        )

    return StreamingResponse(
        stream_allocations_delta(
            role="state",
            role_code=state_code,
            fetcher=_fetch,
            interval_seconds=interval,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/allocations/summary")
def state_allocations_summary(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    limit, offset = _pagination(page, page_size)
    started = time.perf_counter() * 1000.0
    payload = get_state_allocation_summary(db, user["state_code"])
    rows = list((payload or {}).get("rows") or [])[offset:offset + limit]
    payload["rows"] = rows
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/state/allocations/summary",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
        extra={"state_code": str(user["state_code"])},
    )
    return payload


@router.get("/run-history")
def state_run_history(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    limit, offset = _pagination(page, page_size)
    started = time.perf_counter() * 1000.0
    rows = get_state_run_history(db, user["state_code"], limit=limit, offset=offset)
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/state/run-history",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
        extra={"state_code": str(user["state_code"])},
    )
    return rows


@router.get("/unmet")
def state_unmet(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    limit, offset = _pagination(page, page_size)
    return get_state_unmet(db, user["state_code"], limit=limit, offset=offset)


@router.get("/escalations")
def state_escalations(
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    return get_state_escalation_candidates(db, user["state_code"])


@router.post("/escalations/{request_id}")
def escalate_to_national(
    request_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    return escalate_request_to_national(
        db=db,
        request_id=request_id,
        actor_state=user["state_code"],
        reason=(data or {}).get("reason")
    )




@router.get("/pool")
def state_pool(
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    started = time.perf_counter() * 1000.0
    rows = get_state_pool_balance(db, user["state_code"])
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/state/pool",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
        extra={"state_code": str(user["state_code"])},
    )
    return rows


@router.get("/pool/transactions")
def state_pool_transactions(
    limit: int = 200,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    started = time.perf_counter() * 1000.0
    rows = list_state_pool_transactions(db, user["state_code"], limit=limit)
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/state/pool/transactions",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
        extra={"state_code": str(user["state_code"])},
    )
    return rows


@router.post("/pool/allocate")
def state_pool_allocate(
    payload: PoolAllocateCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    try:
        tx = allocate_from_state_pool(
            db=db,
            actor_state=user["state_code"],
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


@router.get("/mutual-aid/requests")
def state_mutual_aid_requests(
    include_closed: bool = False,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    rows = list_requests_for_state(db, user["state_code"], include_closed=bool(include_closed))
    return [
        {
            "id": int(r.id),
            "requesting_state": r.requesting_state,
            "requesting_district": r.requesting_district,
            "resource_id": r.resource_id,
            "quantity_requested": float(r.quantity_requested or 0.0),
            "time": int(r.time),
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/mutual-aid/market")
def state_mutual_aid_market(
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    return list_market_requests_for_offering_state(db, user["state_code"])


@router.post("/mutual-aid/offers")
def state_create_mutual_aid_offer(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    from fastapi import HTTPException

    try:
        row = create_mutual_aid_offer(
            db=db,
            request_id=int((payload or {}).get("request_id")),
            offering_state=str(user["state_code"]),
            quantity_offered=float((payload or {}).get("quantity_offered", 0.0)),
            cap_quantity=(None if (payload or {}).get("cap_quantity") is None else float((payload or {}).get("cap_quantity"))),
        )
        return {
            "status": "ok",
            "offer_id": int(row.id),
            "request_id": int(row.request_id),
            "offering_state": row.offering_state,
            "quantity_offered": float(row.quantity_offered or 0.0),
            "offer_status": row.status,
        }
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/mutual-aid/offers/{offer_id}/respond")
def state_respond_to_mutual_aid_offer(
    offer_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    from fastapi import HTTPException

    try:
        row = respond_to_offer(
            db=db,
            offer_id=int(offer_id),
            decision=str((payload or {}).get("decision", "")).strip().lower(),
            actor_state=str(user["state_code"]),
        )
        return {
            "status": "ok",
            "offer_id": int(row.id),
            "request_id": int(row.request_id),
            "offer_status": row.status,
        }
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/agent/recommendations")
def state_agent_recommendations(
    status: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    limit, offset = _pagination(page, page_size)
    statuses = None
    if status:
        statuses = [s.strip().lower() for s in str(status).split(",") if s.strip()]

    started = time.perf_counter() * 1000.0
    rows = list_recommendations(db, statuses=statuses, limit=limit, offset=offset)
    district_codes = {
        str(row.district_code)
        for row in db.query(District).filter(District.state_code == str(user["state_code"])).all()
    }

    finding_ids = [int(r.finding_id) for r in rows if r.finding_id is not None]
    finding_map = {
        int(f.id): f for f in db.query(AgentFinding).filter(AgentFinding.id.in_(finding_ids)).all()
    } if finding_ids else {}

    out = []
    for r in rows:
        finding = finding_map.get(int(r.finding_id)) if r.finding_id is not None else None
        payload = dict(r.payload_json or {})
        district_code = str(payload.get("district_code") or r.district_code or "")
        if district_code and district_code not in district_codes:
            continue
        out.append({
            "id": int(r.id),
            "finding_id": int(r.finding_id) if r.finding_id is not None else None,
            "entity_type": None if finding is None else finding.entity_type,
            "entity_id": None if finding is None else finding.entity_id,
            "finding_type": None if finding is None else finding.finding_type,
            "severity": None if finding is None else finding.severity,
            "evidence_json": None if finding is None else finding.evidence_json,
            "recommendation_type": r.recommendation_type or r.action_type,
            "payload_json": r.payload_json,
            "message": r.message,
            "status": r.status,
            "created_at": r.created_at,
        })
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/state/agent/recommendations",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(out),
        extra={"state_code": str(user["state_code"])},
    )
    return out


@router.post("/agent/recommendations/{recommendation_id}/decision")
def state_decide_agent_recommendation(
    recommendation_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["state"]))
):
    row = decide_recommendation(
        db=db,
        recommendation_id=int(recommendation_id),
        decision=str((data or {}).get("decision", "")),
        actor=user,
    )
    return {
        "status": "ok",
        "id": int(row.id),
        "recommendation_status": row.status,
    }
