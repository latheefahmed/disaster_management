from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.database import Base


class StockRefillTransaction(Base):
    __tablename__ = "stock_refill_transactions"

    id = Column(Integer, primary_key=True)
    scope = Column(String, nullable=False)  # district | state | national
    district_code = Column(String, nullable=True)
    state_code = Column(String, nullable=True)
    resource_id = Column(String, nullable=False)
    quantity_delta = Column(Float, nullable=False)
    reason = Column(String, nullable=False)
    actor_role = Column(String, nullable=False)
    actor_id = Column(String, nullable=False)
    source = Column(String, nullable=False, default="manual_refill")  # manual_refill | solver_allocation_debit
    solver_run_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
