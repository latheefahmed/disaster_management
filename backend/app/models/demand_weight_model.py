from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.database import Base


class DemandWeightModel(Base):
    __tablename__ = "demand_weight_models"

    id = Column(Integer, primary_key=True)
    district_code = Column(String, nullable=True)
    resource_id = Column(String, nullable=True)
    time_slot = Column(Integer, nullable=True)

    w_baseline = Column(Float, nullable=False)
    w_human = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)

    trained_on_start = Column(DateTime, nullable=True)
    trained_on_end = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
