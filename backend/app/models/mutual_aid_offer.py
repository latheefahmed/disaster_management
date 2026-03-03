from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from datetime import datetime

from app.database import Base


class MutualAidOffer(Base):
    __tablename__ = "mutual_aid_offers"

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("mutual_aid_requests.id"), nullable=False, index=True)
    offering_state = Column(String, nullable=False, index=True)
    quantity_offered = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
