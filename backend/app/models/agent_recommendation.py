from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON
from app.database import Base


class AgentRecommendation(Base):
    __tablename__ = "agent_recommendations"

    id = Column(Integer, primary_key=True)
    finding_id = Column(Integer, nullable=True)
    scenario_id = Column(Integer, nullable=True)
    solver_run_id = Column(Integer, nullable=True)

    district_code = Column(String, nullable=True)
    resource_id = Column(String, nullable=True)

    recommendation_type = Column(String, nullable=True)
    payload_json = Column(JSON, nullable=True)
    action_type = Column(String, nullable=False)
    message = Column(String, nullable=False)
    requires_confirmation = Column(Boolean, default=True)
    status = Column(String, default="pending")

    created_at = Column(DateTime, default=datetime.utcnow)
