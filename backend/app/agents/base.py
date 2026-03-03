from abc import ABC, abstractmethod
from sqlalchemy.orm import Session
from app.services.audit_service import log_event


class BaseAgent(ABC):
    def __init__(self, db: Session, actor: dict):
        self.db = db
        self.actor = actor

    @property
    def role(self):
        return self.actor.get("role")

    def audit(self, event_type: str, payload: dict):
        log_event(
            actor_role=self.role,
            actor_id=(
                self.actor.get("district_code")
                or self.actor.get("state_code")
                or "national"
            ),
            event_type=event_type,
            payload=payload
        )

    # -------------------------
    # AGENT POLICY HOOK
    # -------------------------

    def propose_adjustment(self, demand_row: dict) -> dict:
        """
        Override in child agents.
        Input: {district_code, resource_id, time, demand}
        Output: same schema
        """
        return demand_row

    @abstractmethod
    def handle(self, *args, **kwargs):
        pass
