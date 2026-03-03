from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, CheckConstraint
from datetime import datetime
from app.database import Base


class Allocation(Base):
    __tablename__ = "allocations"
    __table_args__ = (
        CheckConstraint("allocated_quantity >= 0", name="ck_allocations_non_negative"),
        CheckConstraint("is_unmet IN (0,1)", name="ck_allocations_is_unmet_bool"),
    )

    id = Column(Integer, primary_key=True)

    solver_run_id = Column(Integer, ForeignKey("solver_runs.id"), nullable=False)

    request_id = Column(Integer, nullable=False, default=0)
    source_request_id = Column(Integer, nullable=True)
    source_request_created_at = Column(DateTime, nullable=True)
    source_batch_id = Column(Integer, nullable=True)
    supply_level = Column(String, nullable=False, default="district")
    allocation_source_scope = Column(String, nullable=True)
    allocation_source_code = Column(String, nullable=True)

    resource_id = Column(String, nullable=False)

    district_code = Column(String, nullable=False)
    state_code = Column(String, nullable=True)
    origin_state = Column(String, nullable=True)
    origin_state_code = Column(String, nullable=True)
    origin_district_code = Column(String, nullable=True)

    time = Column(Integer, nullable=False)

    allocated_quantity = Column(Float, nullable=False)
    implied_delay_hours = Column(Float, nullable=True)
    receipt_confirmed = Column(Boolean, nullable=False, default=False)
    receipt_time = Column(DateTime, nullable=True)

    is_unmet = Column(Boolean, default=False)
    claimed_quantity = Column(Float, nullable=False, default=0.0)
    consumed_quantity = Column(Float, nullable=False, default=0.0)
    returned_quantity = Column(Float, nullable=False, default=0.0)
    status = Column(String, nullable=False, default="allocated")
    overflow_reconciled_at = Column(DateTime, nullable=True)
    overflow_reconcile_mode = Column(String, nullable=True)
    overflow_reconcile_run_id = Column(String, nullable=True)
    overflow_reconciled_quantity = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
