from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from datetime import datetime

from app.database import Base


class StateTransfer(Base):
    __tablename__ = "state_transfers"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, ForeignKey("solver_runs.id"), nullable=True, index=True)
    request_id = Column(Integer, ForeignKey("mutual_aid_requests.id"), nullable=True, index=True)
    offer_id = Column(Integer, ForeignKey("mutual_aid_offers.id"), nullable=True, index=True)

    from_state = Column(String, nullable=False, index=True)
    to_state = Column(String, nullable=False, index=True)
    resource_id = Column(String, nullable=False, index=True)
    quantity = Column(Float, nullable=False)
    time = Column(Integer, nullable=False, index=True)

    status = Column(String, nullable=False, default="confirmed", index=True)
    transfer_kind = Column(String, nullable=False, default="aid", index=True)
    consumed_in_run_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
