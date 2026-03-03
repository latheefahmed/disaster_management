from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String

from app.database import Base


class NeuralIncidentLog(Base):
    __tablename__ = "neural_incident_log"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, nullable=True)
    incident_type = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="medium")
    details_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
