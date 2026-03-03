from sqlalchemy import Column, Integer, String, DateTime, Text
from datetime import datetime
from app.database import Base


class SolverRun(Base):
    __tablename__ = "solver_runs"

    id = Column(Integer, primary_key=True)

    scenario_id = Column(Integer, nullable=True)   # null = live
    mode = Column(String, nullable=False)          # live | scenario
    status = Column(String, default="running")     # running | completed | failed

    demand_snapshot_path = Column(String, nullable=True)
    summary_snapshot_json = Column(Text, nullable=True)
    weight_model_id = Column(Integer, nullable=True)
    priority_model_id = Column(Integer, nullable=True)
    urgency_model_id = Column(Integer, nullable=True)

    started_at = Column(DateTime, default=datetime.utcnow)
