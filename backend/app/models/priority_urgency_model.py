from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String

from app.database import Base


class PriorityUrgencyModel(Base):
    __tablename__ = "priority_urgency_models"

    id = Column(Integer, primary_key=True)
    resource_id = Column(String, nullable=True)
    district_code = Column(String, nullable=True)

    model_type = Column(String, nullable=False)  # priority | urgency
    version = Column(Integer, nullable=False, default=1)

    trained_on_start = Column(DateTime, nullable=True)
    trained_on_end = Column(DateTime, nullable=True)
    metrics_json = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow)
