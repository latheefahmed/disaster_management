from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.database import Base


class PoolTransaction(Base):
    __tablename__ = "pool_transactions"

    id = Column(Integer, primary_key=True)
    state_code = Column(String, nullable=True)
    district_code = Column(String, nullable=True)
    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)
    quantity_delta = Column(Float, nullable=False)
    reason = Column(String, nullable=False)
    actor_role = Column(String, nullable=False)
    actor_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
