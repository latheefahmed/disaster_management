from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from datetime import datetime
from app.database import Base


class ShipmentPlan(Base):
    __tablename__ = "shipment_plans"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, ForeignKey("solver_runs.id"), nullable=False)
    from_district = Column(String, nullable=False)
    to_district = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)
    quantity = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="planned")
    created_at = Column(DateTime, default=datetime.utcnow)
