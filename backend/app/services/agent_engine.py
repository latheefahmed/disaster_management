from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import ENABLE_AGENT_ENGINE
from app.models.agent_action_log import AgentActionLog
from app.models.agent_finding import AgentFinding
from app.models.agent_recommendation import AgentRecommendation
from app.services.mutual_aid_service import create_mutual_aid_request
from app.services.signal_service import generate_signals


def _finding_exists(db: Session, finding_type: str, entity_type: str, entity_id: str, resource_id: str | None = None) -> bool:
    rows = db.query(AgentFinding).filter(
        AgentFinding.finding_type == str(finding_type),
        AgentFinding.entity_type == str(entity_type),
        AgentFinding.entity_id == str(entity_id),
    ).order_by(AgentFinding.id.desc()).limit(25).all()
    if not resource_id:
        return len(rows) > 0
    needle = str(resource_id)
    for row in rows:
        evidence = dict(row.evidence_json or {})
        if str(evidence.get("resource_id") or "") == needle:
            return True
    return False


def _create_recommendation_for_signal(db: Session, finding: AgentFinding, signal: dict):
    signal_type = str(signal.get("signal_type"))
    entity_id = str(signal.get("entity_id"))
    resource_id = signal.get("resource_id")
    evidence = dict(signal.get("evidence") or {})

    if signal_type == "chronic_unmet":
        rec_type = "switch_demand_mode"
        payload = {
            "district_code": entity_id,
            "target_demand_mode": "baseline_plus_human",
            "suggested_priority": 3,
            "resource_id": resource_id,
        }
        message = f"District {entity_id} has chronic unmet demand for {resource_id}; suggest demand_mode baseline_plus_human and priority floor 3."
    elif signal_type == "chronic_delay":
        rec_type = "suggest_neighbor_state_sourcing"
        payload = {
            "district_code": entity_id,
            "resource_id": resource_id,
            "time": int(evidence.get("latest_time") or 1),
            "quantity_requested": float(evidence.get("unmet_total") or 1.0),
        }
        message = f"District {entity_id} shows chronic delay for {resource_id}; suggest neighbor-state sourcing via mutual aid."
    else:
        rec_type = "raise_baseline_weight"
        payload = {
            "district_code": entity_id,
            "target_demand_mode": "baseline_plus_human",
            "note": "Repeated overrides detected",
        }
        message = f"District {entity_id} has repeated overrides; suggest raising baseline influence (Phase 6 governance)."

    row = AgentRecommendation(
        finding_id=int(finding.id),
        recommendation_type=rec_type,
        payload_json=payload,
        status="pending",
        district_code=payload.get("district_code") if isinstance(payload, dict) else None,
        resource_id=str(resource_id) if resource_id is not None else None,
        action_type=rec_type,
        message=message,
        requires_confirmation=True,
    )
    db.add(row)


def run_agent_engine(db: Session, trigger: str, context: dict | None = None) -> dict:
    if not ENABLE_AGENT_ENGINE:
        return {"enabled": False, "findings_created": 0, "recommendations_created": 0}

    context_data = dict(context or {})

    signals = generate_signals(db)
    findings_created = 0
    recommendations_created = 0

    for signal in signals:
        signal_type = str(signal.get("signal_type"))
        entity_type = str(signal.get("entity_type"))
        entity_id = str(signal.get("entity_id"))
        resource_id = signal.get("resource_id")

        if _finding_exists(db, signal_type, entity_type, entity_id, str(resource_id) if resource_id else None):
            continue

        evidence = dict(signal.get("evidence") or {})
        if resource_id is not None:
            evidence["resource_id"] = str(resource_id)
        evidence["trigger"] = str(trigger)
        evidence["context"] = context_data

        finding = AgentFinding(
            entity_type=entity_type,
            entity_id=entity_id,
            finding_type=signal_type,
            severity=str(signal.get("severity") or "low"),
            evidence_json=evidence,
        )
        db.add(finding)
        db.flush()
        findings_created += 1

        _create_recommendation_for_signal(db, finding, signal)
        recommendations_created += 1

    db.commit()
    return {
        "enabled": True,
        "signals_seen": len(signals),
        "findings_created": findings_created,
        "recommendations_created": recommendations_created,
    }


def list_recommendations(
    db: Session,
    statuses: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
):
    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))
    query = db.query(AgentRecommendation)
    if statuses:
        query = query.filter(AgentRecommendation.status.in_(statuses))
    return query.order_by(AgentRecommendation.created_at.desc(), AgentRecommendation.id.desc()).offset(safe_offset).limit(safe_limit).all()


def _record_action(db: Session, recommendation_id: int, action_taken: str, actor_user_id: str):
    db.add(AgentActionLog(
        recommendation_id=int(recommendation_id),
        action_taken=str(action_taken),
        actor_user_id=str(actor_user_id),
    ))


def _apply_recommendation(db: Session, rec: AgentRecommendation, actor: dict):
    from app.services.request_service import set_district_demand_mode

    payload = dict(rec.payload_json or {})
    rec_type = str(rec.recommendation_type or "")

    if rec_type in {"switch_demand_mode", "raise_baseline_weight"}:
        district_code = str(payload.get("district_code") or rec.district_code or "")
        if district_code:
            target_mode = str(payload.get("target_demand_mode") or "baseline_plus_human")
            set_district_demand_mode(db, district_code=district_code, demand_mode=target_mode)
        _record_action(db, rec.id, "applied_demand_mode_update", actor.get("username", "unknown"))
        return

    if rec_type == "suggest_neighbor_state_sourcing":
        district_code = str(payload.get("district_code") or rec.district_code or "")
        resource_id = str(payload.get("resource_id") or rec.resource_id or "")
        state_code = str(actor.get("state_code") or "")
        if district_code and resource_id and state_code:
            create_mutual_aid_request(
                db=db,
                requesting_state=state_code,
                requesting_district=district_code,
                resource_id=resource_id,
                quantity_requested=float(payload.get("quantity_requested") or 1.0),
                time=int(payload.get("time") or 1),
            )
        _record_action(db, rec.id, "created_mutual_aid_request", actor.get("username", "unknown"))
        return

    _record_action(db, rec.id, "approved_noop_unknown_type", actor.get("username", "unknown"))


def decide_recommendation(db: Session, recommendation_id: int, decision: str, actor: dict):
    rec = db.query(AgentRecommendation).filter(AgentRecommendation.id == int(recommendation_id)).first()
    if rec is None:
        raise ValueError("Recommendation not found")

    normalized = str(decision or "").strip().lower()
    if normalized not in {"approved", "rejected"}:
        raise ValueError("Decision must be approved or rejected")

    rec.status = normalized

    if normalized == "approved":
        _apply_recommendation(db, rec, actor)
    else:
        _record_action(db, rec.id, "rejected", actor.get("username", "unknown"))

    db.commit()
    db.refresh(rec)
    return rec
