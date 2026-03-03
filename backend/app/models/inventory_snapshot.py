from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from datetime import datetime
from app.database import Base


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, ForeignKey("solver_runs.id"), nullable=False)
    district_code = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)
    quantity = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
