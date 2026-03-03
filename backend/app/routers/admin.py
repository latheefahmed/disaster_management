from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.services.scenario_service import (
    create_scenario,
    add_scenario_request,
    add_scenario_demand_batch,
    add_state_stock_override,
    add_national_stock_override,
    list_scenarios,
    get_scenario_detail,
    get_scenario_runs,
    get_scenario_analysis,
    get_scenario_run_summary,
    get_scenario_run_incidents,
)
from app.services.scenario_runner import run_scenario
from app.services.scenario_control_service import (
    finalize_scenario,
    clone_scenario_as_new,
    build_randomizer_preview,
    apply_randomizer_to_scenario,
    revert_scenario_effects,
    verify_scenario_revert_balance,
)
from app.services.agent_engine import list_recommendations, decide_recommendation
from app.models.agent_finding import AgentFinding
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


@router.post("/scenarios")
def create_new_scenario(
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return create_scenario(db, data["name"])


@router.get("/scenarios")
def list_all_scenarios(
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return list_scenarios(db)


@router.get("/scenarios/{scenario_id}")
def scenario_detail(
    scenario_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return get_scenario_detail(db, scenario_id)


@router.get("/scenarios/{scenario_id}/runs")
def scenario_runs(
    scenario_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return get_scenario_runs(db, scenario_id)


@router.get("/scenarios/{scenario_id}/analysis")
def scenario_analysis(
    scenario_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return get_scenario_analysis(db, scenario_id)


@router.get("/scenarios/{scenario_id}/runs/{run_id}/summary")
def scenario_run_summary(
    scenario_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return get_scenario_run_summary(db, scenario_id, run_id)


@router.get("/scenarios/{scenario_id}/runs/incidents")
def scenario_run_incidents(
    scenario_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return get_scenario_run_incidents(db, scenario_id, limit=limit)


@router.post("/scenarios/{scenario_id}/add-demand")
def add_demand(
    scenario_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return add_scenario_request(db, scenario_id, data)


@router.post("/scenarios/{scenario_id}/add-demand-batch")
def add_demand_batch(
    scenario_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    rows = (data or {}).get("rows", [])
    return add_scenario_demand_batch(db, scenario_id, rows)


@router.post("/scenarios/{scenario_id}/set-state-stock")
def set_state_stock(
    scenario_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return add_state_stock_override(db, scenario_id, data)


@router.post("/scenarios/{scenario_id}/set-national-stock")
def set_national_stock(
    scenario_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return add_national_stock_override(db, scenario_id, data)


@router.post("/scenarios/{scenario_id}/run")
def run_scenario_endpoint(
    scenario_id: int,
    data: dict | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    try:
        payload = data or {}
        run_scenario(db, scenario_id, scope_mode=str(payload.get("scope_mode") or "focused"))
        return {"status": "scenario completed"}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"scenario_run_failed:{type(exc).__name__}:{exc}")


@router.post("/scenarios/{scenario_id}/finalize")
def finalize_scenario_endpoint(
    scenario_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return finalize_scenario(db, scenario_id)


@router.post("/scenarios/{scenario_id}/clone")
def clone_scenario_endpoint(
    scenario_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return clone_scenario_as_new(db, scenario_id, name=(data or {}).get("name"))


@router.post("/scenarios/{scenario_id}/randomizer/preview")
def randomizer_preview_endpoint(
    scenario_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return build_randomizer_preview(db, scenario_id, config=(data or {}))


@router.post("/scenarios/{scenario_id}/randomizer/apply")
def randomizer_apply_endpoint(
    scenario_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return apply_randomizer_to_scenario(db, scenario_id, config=(data or {}))


@router.post("/scenarios/{scenario_id}/revert-effects")
def revert_scenario_effects_endpoint(
    scenario_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    run_id = (data or {}).get("run_id")
    return revert_scenario_effects(db, scenario_id, run_id=(None if run_id in (None, "") else int(run_id)))


@router.get("/scenarios/{scenario_id}/revert-effects/verify")
def verify_scenario_revert_endpoint(
    scenario_id: int,
    run_id: int | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return verify_scenario_revert_balance(db, scenario_id, run_id=run_id)


@router.get("/agent/recommendations")
def list_agent_recommendations(
    status: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    limit, offset = _pagination(page, page_size)
    statuses = None
    if status:
        statuses = [s.strip().lower() for s in str(status).split(",") if s.strip()]

    started = time.perf_counter() * 1000.0
    rows = list_recommendations(db, statuses=statuses, limit=limit, offset=offset)
    finding_ids = [int(r.finding_id) for r in rows if r.finding_id is not None]
    finding_map = {
        int(f.id): f for f in db.query(AgentFinding).filter(AgentFinding.id.in_(finding_ids)).all()
    } if finding_ids else {}

    out = []
    for r in rows:
        finding = finding_map.get(int(r.finding_id)) if r.finding_id is not None else None
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
        endpoint="/admin/agent/recommendations",
        total_ms=total_ms,
        db_ms=total_ms,
        rows_scanned=len(rows),
        rows_returned=len(out),
    )
    return out


@router.post("/agent/recommendations/{recommendation_id}/decision")
def decide_agent_recommendation(
    recommendation_id: int,
    data: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
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
