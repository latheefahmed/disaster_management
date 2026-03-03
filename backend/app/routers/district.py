import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.schemas.request import RequestCreate
from app.schemas.allocation import AllocationOut
from app.schemas.district import (
    DemandModeUpdate,
    DistrictOut,
    ClaimCreate,
    ConsumptionCreate,
    ReturnCreate,
)

from app.services.request_service import (
    create_request,
    create_request_batch,
    trigger_live_solver_run,
    get_district_requests_view,
    get_district_demand_mode,
    to_ui_demand_mode,
    set_district_demand_mode
)
from app.services.action_service import (
    create_claim,
    create_consumption,
    create_return,
    list_claims_for_district,
    list_consumption_for_district,
    list_returns_for_district,
)
from app.services.mutual_aid_service import create_mutual_aid_request
from app.services.allocation_service import confirm_allocation_receipt
from app.services.allocation_service import get_latest_completed_run
from app.services.agent_engine import run_agent_engine
from app.config import ENABLE_RECEIPT_CONFIRMATION, ENABLE_AGENT_ENGINE
from app.utils.security import get_token_payload, require_roles
from app.schemas.kpi import KPIOut
from app.schemas.stock import StockRowOut
from app.schemas.stock_refill import StockRefillCreate
from app.services.kpi_service import compute_district_kpis, get_district_stock_rows
from app.services.stock_refill_service import create_stock_refill

from app.models.allocation import Allocation
from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
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


# -------------------------------
# Helpers
# -------------------------------

def get_allocations_for_district(db: Session, district_code: str, limit: int = 100, offset: int = 0):
    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))
    run_rows = db.query(Allocation.solver_run_id)\
        .join(SolverRun, SolverRun.id == Allocation.solver_run_id)\
        .filter(
            Allocation.district_code == district_code,
            Allocation.is_unmet == False,
            SolverRun.status == "completed",
            SolverRun.mode == "live",
        )\
        .group_by(Allocation.solver_run_id)\
        .order_by(Allocation.solver_run_id.desc())\
        .limit(200)\
        .all()
    run_ids = [int(r[0]) for r in run_rows if r and r[0] is not None]
    if not run_ids:
        return []

    return db.query(Allocation)\
        .join(SolverRun, SolverRun.id == Allocation.solver_run_id)\
        .outerjoin(ResourceRequest, ResourceRequest.id == Allocation.request_id)\
        .filter(
            Allocation.district_code == district_code,
            Allocation.is_unmet == False,
            SolverRun.status == "completed",
            SolverRun.mode == "live",
            Allocation.solver_run_id.in_(run_ids),
        )\
        .order_by(
            Allocation.solver_run_id.desc(),
            Allocation.created_at.desc(),
            Allocation.id.desc(),
        )\
        .offset(safe_offset)\
        .limit(safe_limit)\
        .all()


def get_allocations_for_district_cursor(db: Session, district_code: str, cursor_id: int | None = None, limit: int = 300):
    safe_limit = max(1, min(300, int(limit or 300)))
    query = db.query(Allocation)\
        .join(SolverRun, SolverRun.id == Allocation.solver_run_id)\
        .outerjoin(ResourceRequest, ResourceRequest.id == Allocation.request_id)\
        .filter(
            Allocation.district_code == district_code,
            Allocation.is_unmet == False,
            SolverRun.status == "completed",
        )

    if cursor_id is not None:
        query = query.filter(Allocation.id < int(cursor_id))

    rows = query.order_by(
        Allocation.solver_run_id.desc(),
        func.coalesce(ResourceRequest.created_at, Allocation.created_at).desc(),
        ResourceRequest.id.desc(),
        Allocation.time.asc(),
        Allocation.id.desc(),
    ).limit(safe_limit).all()
    return {"rows": rows, "next_cursor": (None if len(rows) < safe_limit else int(rows[-1].id))}


def get_allocations_for_district_delta(
    db: Session,
    district_code: str,
    since_run_id: int = 0,
    since_allocation_id: int = 0,
    limit: int = 300,
):
    safe_limit = max(1, min(300, int(limit or 300)))
    since_run = max(0, int(since_run_id or 0))
    since_alloc = max(0, int(since_allocation_id or 0))

    rows = db.query(Allocation)\
        .join(SolverRun, SolverRun.id == Allocation.solver_run_id)\
        .filter(
            Allocation.district_code == district_code,
            Allocation.is_unmet == False,
            SolverRun.status == "completed",
            (
                (Allocation.solver_run_id > since_run)
                | ((Allocation.solver_run_id == since_run) & (Allocation.id > since_alloc))
            ),
        )\
        .order_by(Allocation.solver_run_id.asc(), Allocation.id.asc())\
        .limit(safe_limit)\
        .all()

    latest_run = (max((int(r.solver_run_id) for r in rows), default=since_run) if rows else since_run)
    latest_alloc = (max((int(r.id) for r in rows), default=since_alloc) if rows else since_alloc)
    return {"rows": rows, "latest_run_id": latest_run, "latest_allocation_id": latest_alloc}


def get_unmet_for_district(db: Session, district_code: str, limit: int = 100, offset: int = 0):
    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))
    run_rows = db.query(Allocation.solver_run_id)\
        .join(SolverRun, SolverRun.id == Allocation.solver_run_id)\
        .filter(
            Allocation.district_code == district_code,
            Allocation.is_unmet == True,
            SolverRun.status == "completed",
            SolverRun.mode == "live",
        )\
        .group_by(Allocation.solver_run_id)\
        .order_by(Allocation.solver_run_id.desc())\
        .limit(200)\
        .all()
    run_ids = [int(r[0]) for r in run_rows if r and r[0] is not None]
    if not run_ids:
        return []
    rows = db.query(Allocation)\
        .join(SolverRun, SolverRun.id == Allocation.solver_run_id)\
        .filter(
            Allocation.district_code == district_code,
            Allocation.is_unmet == True,
            SolverRun.status == "completed",
            SolverRun.mode == "live",
            Allocation.solver_run_id.in_(run_ids),
        )\
        .order_by(Allocation.solver_run_id.desc(), Allocation.created_at.desc(), Allocation.id.desc())\
        .offset(safe_offset)\
        .limit(safe_limit)\
        .all()

    return [{
        "id": r.id,
        "solver_run_id": r.solver_run_id,
        "resource_id": r.resource_id,
        "district_code": r.district_code,
        "time": r.time,
        "unmet_quantity": r.allocated_quantity,
    } for r in rows]


def get_run_history_for_district(db: Session, district_code: str, limit: int = 100, offset: int = 0):
    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))
    runs = db.query(SolverRun).filter(SolverRun.status == "completed").order_by(SolverRun.id.desc()).offset(safe_offset).limit(safe_limit).all()
    if not runs:
        return []

    out = []
    for run in runs:
        rid = int(run.id)
        allocated = 0.0
        unmet = 0.0
        raw = getattr(run, "summary_snapshot_json", None)
        if raw:
            try:
                snap = json.loads(str(raw))
                if isinstance(snap, dict):
                    district_totals = (snap.get("district_totals") or {}).get(str(district_code)) or {}
                    allocated = float(district_totals.get("allocated_quantity") or 0.0)
                    unmet = float(district_totals.get("unmet_quantity") or 0.0)
            except Exception:
                pass
        out.append({
            "run_id": rid,
            "status": str(run.status),
            "mode": str(run.mode),
            "started_at": run.started_at,
            "total_demand": float(allocated + unmet),
            "total_allocated": allocated,
            "total_unmet": unmet,
        })
    return out


# -------------------------------
# Profile
# -------------------------------

@router.get("/me", response_model=DistrictOut)
def district_me(
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    d = db.query(District)\
        .filter(District.district_code == user["district_code"])\
        .first()

    if not d:
        raise HTTPException(status_code=404, detail="District not found")

    return d


# -------------------------------
# Demand Mode
# -------------------------------

@router.get("/demand-mode")
def get_my_demand_mode(
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    mode = get_district_demand_mode(db, user["district_code"])
    return {
        "district_code": user["district_code"],
        "demand_mode": mode,
        "ui_mode": to_ui_demand_mode(mode),
    }


@router.put("/demand-mode")
def update_my_demand_mode(
    payload: DemandModeUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    out = set_district_demand_mode(
        db,
        user["district_code"],
        payload.demand_mode
    )
    out["ui_mode"] = to_ui_demand_mode(out["demand_mode"])
    return out


# -------------------------------
# Requests
# -------------------------------

@router.post("/request", status_code=201)
def create_district_request(
    data: RequestCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    try:
        return create_request(db, user, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/request-batch")
def create_district_request_batch(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    items = (payload or {}).get("items", [])
    try:
        return create_request_batch(db, user, items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/requests")
def list_my_requests(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    time: int | None = None,
    day: str | None = None,
    latest_only: bool = False,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    limit, offset = _pagination(page, page_size)
    return get_district_requests_view(
        db=db,
        district_code=user["district_code"],
        time_filter=time,
        day_filter=day,
        latest_only=latest_only,
        limit=limit,
        offset=offset,
    )


# -------------------------------
# Allocations
# -------------------------------

@router.get("/allocations", response_model=list[AllocationOut])
def list_my_allocations(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    limit, offset = _pagination(page, page_size)
    started = time.perf_counter() * 1000.0
    rows = get_allocations_for_district(
        db,
        user["district_code"],
        limit=limit,
        offset=offset,
    )
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/district/allocations",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
        extra={"district_code": str(user["district_code"])},
    )
    return rows


@router.get("/allocations/cursor")
def list_my_allocations_cursor(
    cursor_id: int | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    limit, _ = _pagination(1, page_size)
    payload = get_allocations_for_district_cursor(
        db,
        user["district_code"],
        cursor_id=cursor_id,
        limit=limit,
    )
    return {
        "rows": payload["rows"],
        "next_cursor": payload["next_cursor"],
    }


@router.get("/allocations/delta")
def list_my_allocations_delta(
    since_run_id: int = 0,
    since_allocation_id: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    limit, _ = _pagination(1, page_size)
    payload = get_allocations_for_district_delta(
        db,
        user["district_code"],
        since_run_id=since_run_id,
        since_allocation_id=since_allocation_id,
        limit=limit,
    )
    return payload


@router.get("/allocations/stream")
async def stream_my_allocations(
    token: str = Query(...),
    interval: float = 1.5,
    db: Session = Depends(get_db),
):
    user = _require_stream_role(token, ["district"])
    district_code = str(user.get("district_code") or "")

    def _fetch(since_run_id: int, since_allocation_id: int):
        return get_allocations_for_district_delta(
            db,
            district_code,
            since_run_id=since_run_id,
            since_allocation_id=since_allocation_id,
            limit=300,
        )

    return StreamingResponse(
        stream_allocations_delta(
            role="district",
            role_code=district_code,
            fetcher=_fetch,
            interval_seconds=interval,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/solver-status")
def get_district_solver_status(
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    selected_run = get_latest_completed_run(db)

    if not selected_run:
        return {
            "solver_run_id": None,
            "status": "idle",
            "mode": "live"
        }

    alloc_count = db.query(Allocation)\
        .filter(
            Allocation.solver_run_id == selected_run.id,
            Allocation.district_code == user["district_code"],
            Allocation.is_unmet == False
        )\
        .count()

    unmet_count = db.query(Allocation)\
        .filter(
            Allocation.solver_run_id == selected_run.id,
            Allocation.district_code == user["district_code"],
            Allocation.is_unmet == True
        )\
        .count()

    return {
        "solver_run_id": selected_run.id,
        "status": selected_run.status,
        "mode": selected_run.mode,
        "alloc_count": alloc_count,
        "unmet_count": unmet_count,
        "started_at": selected_run.started_at,
    }


@router.get("/run-history")
def district_run_history(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    limit, offset = _pagination(page, page_size)
    started = time.perf_counter() * 1000.0
    rows = get_run_history_for_district(db, str(user["district_code"]), limit=limit, offset=offset)
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/district/run-history",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(rows),
        extra={"district_code": str(user["district_code"])},
    )
    return rows


@router.get("/kpis", response_model=KPIOut)
def district_kpis(
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    started = time.perf_counter() * 1000.0
    payload = compute_district_kpis(db, str(user["district_code"]))
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/district/kpis",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=1,
        rows_returned=1,
        extra={"district_code": str(user["district_code"])},
    )
    return payload


@router.get("/stock", response_model=list[StockRowOut])
def district_stock(
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    return get_district_stock_rows(db, str(user["district_code"]))


@router.post("/stock/refill")
def district_stock_refill(
    payload: StockRefillCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"])),
):
    try:
        row = create_stock_refill(
            db=db,
            scope="district",
            resource_id=payload.resource_id,
            quantity=float(payload.quantity),
            actor_role="district",
            actor_id=str(user["district_code"]),
            district_code=str(user["district_code"]),
            state_code=str(user.get("state_code") or ""),
            note=payload.note,
        )
        return {"status": "ok", "refill_id": int(row.id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# -------------------------------
# UNMET (FIX)
# -------------------------------

@router.get("/unmet")
def list_my_unmet(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    limit, offset = _pagination(page, page_size)
    return get_unmet_for_district(db, user["district_code"], limit=limit, offset=offset)


@router.get("/claims")
def list_my_claims(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    limit, offset = _pagination(page, page_size)
    rows = list_claims_for_district(db, user["district_code"], limit=limit, offset=offset)
    return [
        {
            "id": r.id,
            "district_code": r.district_code,
            "resource_id": r.resource_id,
            "time": r.time,
            "claimed_quantity": float(r.quantity),
            "claimed_by": r.claimed_by,
            "claimed_at": r.created_at,
            "solver_run_id": r.solver_run_id,
        }
        for r in rows
    ]


@router.get("/consumptions")
def list_my_consumptions(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    limit, offset = _pagination(page, page_size)
    rows = list_consumption_for_district(db, user["district_code"], limit=limit, offset=offset)
    return [
        {
            "id": r.id,
            "district_code": r.district_code,
            "resource_id": r.resource_id,
            "time": r.time,
            "consumed_quantity": float(r.quantity),
            "consumed_at": r.created_at,
            "solver_run_id": r.solver_run_id,
        }
        for r in rows
    ]


@router.get("/returns")
def list_my_returns(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    limit, offset = _pagination(page, page_size)
    rows = list_returns_for_district(db, user["district_code"], limit=limit, offset=offset)
    return [
        {
            "id": r.id,
            "district_code": r.district_code,
            "resource_id": r.resource_id,
            "time": r.time,
            "returned_quantity": float(r.quantity),
            "reason": r.reason,
            "returned_at": r.created_at,
            "solver_run_id": r.solver_run_id,
        }
        for r in rows
    ]


@router.post("/claim")
def claim_resource(
    payload: ClaimCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    try:
        row, snapshot = create_claim(
            db,
            district_code=user["district_code"],
            resource_id=payload.resource_id,
            time=payload.time,
            quantity=float(payload.quantity),
            claimed_by=payload.claimed_by or "district_manager",
            solver_run_id=payload.solver_run_id,
        )
        return {"status": "ok", "id": row.id, "snapshot": snapshot}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/consume")
def consume_resource(
    payload: ConsumptionCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    try:
        row, snapshot = create_consumption(
            db,
            district_code=user["district_code"],
            resource_id=payload.resource_id,
            time=payload.time,
            quantity=float(payload.quantity),
            solver_run_id=payload.solver_run_id,
        )
        return {"status": "ok", "id": row.id, "snapshot": snapshot}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/return")
def return_resource(
    payload: ReturnCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    try:
        row, snapshot = create_return(
            db,
            district_code=user["district_code"],
            state_code=user["state_code"],
            resource_id=payload.resource_id,
            time=payload.time,
            quantity=float(payload.quantity),
            reason=payload.reason,
            solver_run_id=payload.solver_run_id,
            allocation_source_scope=payload.allocation_source_scope,
            allocation_source_code=payload.allocation_source_code,
        )
        return {"status": "ok", "id": row.id, "snapshot": snapshot}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/run")
def run_solver_now(
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    run_id = trigger_live_solver_run(db)
    return {
        "status": "accepted",
        "solver_run_id": int(run_id),
        "requested_by": str(user["district_code"]),
    }


@router.post("/allocations/{allocation_id}/confirm")
def confirm_allocation_received(
    allocation_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    if not ENABLE_RECEIPT_CONFIRMATION:
        raise HTTPException(status_code=400, detail="Receipt confirmation is disabled")

    try:
        row = confirm_allocation_receipt(
            db=db,
            allocation_id=int(allocation_id),
            district_code=str(user["district_code"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if ENABLE_AGENT_ENGINE:
        try:
            run_agent_engine(
                db,
                trigger="receipt_confirmation",
                context={
                    "allocation_id": int(row.id),
                    "district_code": str(user["district_code"]),
                },
            )
        except Exception as err:
            print("Agent engine failed on receipt confirmation:", err)

    return {
        "status": "ok",
        "allocation_id": int(row.id),
        "receipt_confirmed": bool(row.receipt_confirmed),
        "receipt_time": row.receipt_time,
    }


@router.post("/mutual-aid/request")
def create_district_mutual_aid_request(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["district"]))
):
    try:
        row = create_mutual_aid_request(
            db=db,
            requesting_state=str(user["state_code"]),
            requesting_district=str(user["district_code"]),
            resource_id=str((payload or {}).get("resource_id", "")).strip(),
            quantity_requested=float((payload or {}).get("quantity_requested", 0.0)),
            time=int((payload or {}).get("time")),
        )
        return {
            "status": "ok",
            "request_id": int(row.id),
            "requesting_state": row.requesting_state,
            "requesting_district": row.requesting_district,
            "resource_id": row.resource_id,
            "quantity_requested": float(row.quantity_requested or 0.0),
            "time": int(row.time),
            "request_status": row.status,
        }
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
