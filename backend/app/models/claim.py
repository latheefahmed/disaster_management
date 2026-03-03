from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy import DateTime
from datetime import datetime
from app.database import Base

class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, ForeignKey("solver_runs.id"), nullable=False, default=0)
    district_code = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    claimed_by = Column(String, nullable=False, default="district_manager")
    created_at = Column(DateTime, default=datetime.utcnow)
