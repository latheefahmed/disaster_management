from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, JSON

from app.database import Base


class AdaptiveParameter(Base):
    __tablename__ = "adaptive_parameters"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, nullable=True)
    source = Column(String, nullable=False, default="fallback")
    mode = Column(String, nullable=False, default="fallback")
    influence_pct = Column(Float, nullable=False, default=0.0)

    alpha = Column(Float, nullable=False)
    beta = Column(Float, nullable=False)
    gamma = Column(Float, nullable=False)
    p_mult = Column(Float, nullable=False)
    u_mult = Column(Float, nullable=False)

    guardrail_passed = Column(Integer, nullable=False, default=1)
    fallback_used = Column(Integer, nullable=False, default=0)
    reason = Column(String, nullable=True)
    guardrail_result = Column(String, nullable=True)

    deterministic_params_json = Column(JSON, nullable=True)
    nn_params_json = Column(JSON, nullable=True)
    applied_params_json = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
