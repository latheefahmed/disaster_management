from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer

from app.database import Base


class NNPrediction(Base):
    __tablename__ = "nn_predictions"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, nullable=True)
    model_version = Column(Integer, nullable=True)

    alpha = Column(Float, nullable=True)
    beta = Column(Float, nullable=True)
    gamma = Column(Float, nullable=True)
    p_mult = Column(Float, nullable=True)
    u_mult = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
