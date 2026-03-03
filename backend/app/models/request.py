from sqlalchemy import Column, Integer, String, Float, DateTime
from datetime import datetime
from app.database import Base


class ResourceRequest(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True)

    district_code = Column(String, nullable=False)
    state_code = Column(String, nullable=False)

    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)

    quantity = Column(Float, nullable=False)
    allocated_quantity = Column(Float, nullable=False, default=0.0)
    unmet_quantity = Column(Float, nullable=False, default=0.0)
    final_demand_quantity = Column(Float, nullable=False, default=0.0)

    priority = Column(Integer, nullable=True)
    urgency = Column(Integer, nullable=True)
    confidence = Column(Float, default=1.0)
    source = Column(String, default="human")

    status = Column(String, default="pending")  # pending | solving | allocated | partial | unmet | failed
    lifecycle_state = Column(String, default="CREATED")
    included_in_run = Column(Integer, default=0)
    queued = Column(Integer, default=1)
    run_id = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
