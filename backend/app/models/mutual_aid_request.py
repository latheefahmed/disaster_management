from sqlalchemy import Column, Integer, String, Float, DateTime
from datetime import datetime

from app.database import Base


class MutualAidRequest(Base):
    __tablename__ = "mutual_aid_requests"

    id = Column(Integer, primary_key=True)
    requesting_state = Column(String, nullable=False, index=True)
    requesting_district = Column(String, nullable=False, index=True)
    resource_id = Column(String, nullable=False, index=True)
    quantity_requested = Column(Float, nullable=False)
    time = Column(Integer, nullable=False, index=True)
    status = Column(String, nullable=False, default="open", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
