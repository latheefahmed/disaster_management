from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer

from app.database import Base


class AdaptiveMetric(Base):
    __tablename__ = "adaptive_metrics"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, nullable=True)
    model_version = Column(Integer, nullable=True)

    unmet_ratio = Column(Float, nullable=True)
    avg_delay_hours = Column(Float, nullable=True)
    volatility = Column(Float, nullable=True)
    stability_score = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
