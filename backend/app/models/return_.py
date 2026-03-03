from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy import DateTime
from datetime import datetime
from app.database import Base

class Return(Base):
    __tablename__ = "returns"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, ForeignKey("solver_runs.id"), nullable=False, default=0)
    district_code = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    reason = Column(String, nullable=False, default="manual")
    created_at = Column(DateTime, default=datetime.utcnow)
