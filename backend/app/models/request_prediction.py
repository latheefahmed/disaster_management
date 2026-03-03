from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer

from app.database import Base


class RequestPrediction(Base):
    __tablename__ = "request_predictions"

    id = Column(Integer, primary_key=True)

    request_id = Column(Integer, ForeignKey("requests.id"), nullable=False)
    predicted_priority = Column(Float, nullable=True)
    predicted_urgency = Column(Float, nullable=True)

    model_id = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)
    explanation_json = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
