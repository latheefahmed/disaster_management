from pydantic import BaseModel
from datetime import datetime


class AuditOut(BaseModel):
    id: int
    actor_role: str
    actor_id: str
    event_type: str
    payload: dict
    created_at: datetime
