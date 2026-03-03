from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String

from app.database import Base


class FinalDemand(Base):
    __tablename__ = "final_demands"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, ForeignKey("solver_runs.id"), nullable=False)

    district_code = Column(String, nullable=False)
    state_code = Column(String, nullable=True)
    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)

    demand_quantity = Column(Float, nullable=False)
    demand_mode = Column(String, nullable=False, default="baseline_plus_human")
    source_mix = Column(String, nullable=False, default="merged")

    created_at = Column(DateTime, default=datetime.utcnow)
