from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String

from app.database import Base


class DemandLearningEvent(Base):
    __tablename__ = "demand_learning_events"

    id = Column(Integer, primary_key=True)

    solver_run_id = Column(Integer, ForeignKey("solver_runs.id"), nullable=False)
    district_code = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)

    baseline_demand = Column(Float, nullable=False)
    human_demand = Column(Float, nullable=False)
    final_demand = Column(Float, nullable=False)
    allocated = Column(Float, nullable=False)
    unmet = Column(Float, nullable=False)

    priority = Column(Float, nullable=False, default=1.0)
    urgency = Column(Float, nullable=False, default=1.0)

    created_at = Column(DateTime, default=datetime.utcnow)
