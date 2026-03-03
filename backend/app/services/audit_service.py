from app.models.audit_log import AuditLog
from app.database import SessionLocal
from sqlalchemy.orm import Session


def log_event(actor_role: str, actor_id: str, event_type: str, payload: dict, db: Session | None = None):
    owns_session = db is None
    session = db or SessionLocal()
    session.add(AuditLog(
        actor_role=actor_role,
        actor_id=actor_id,
        event_type=event_type,
        payload=payload
    ))
    if owns_session:
        session.commit()
        session.close()


def log_entity_event(
    db: Session,
    *,
    user_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict | None,
    after: dict | None,
    actor_role: str,
    actor_id: str,
):
    db.add(
        AuditLog(
            actor_role=actor_role,
            actor_id=actor_id,
            event_type=action,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            payload={
                "before": before,
                "after": after,
            },
        )
    )
