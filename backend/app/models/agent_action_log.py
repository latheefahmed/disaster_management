from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base


class AgentActionLog(Base):
    __tablename__ = "agent_action_log"

    id = Column(Integer, primary_key=True)
    recommendation_id = Column(Integer, nullable=False)
    action_taken = Column(String, nullable=False)
    actor_user_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
