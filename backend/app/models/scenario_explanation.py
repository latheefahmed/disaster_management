from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, JSON
from app.database import Base


class ScenarioExplanation(Base):
    __tablename__ = "scenario_explanations"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, nullable=True)
    solver_run_id = Column(Integer, nullable=True)

    summary = Column(String, nullable=False)
    details = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
