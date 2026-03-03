from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String

from app.database import Base


class PriorityUrgencyEvent(Base):
    __tablename__ = "priority_urgency_events"

    id = Column(Integer, primary_key=True)

    solver_run_id = Column(Integer, ForeignKey("solver_runs.id"), nullable=False)
    district_code = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)

    baseline_demand = Column(Float, nullable=False, default=0.0)
    human_quantity = Column(Float, nullable=False, default=0.0)
    final_demand = Column(Float, nullable=False, default=0.0)
    allocated = Column(Float, nullable=False, default=0.0)
    unmet = Column(Float, nullable=False, default=0.0)

    human_priority = Column(Float, nullable=True)
    human_urgency = Column(Float, nullable=True)

    severity_index = Column(Float, nullable=False, default=0.0)
    infrastructure_damage_index = Column(Float, nullable=False, default=0.0)
    population_exposed = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)
