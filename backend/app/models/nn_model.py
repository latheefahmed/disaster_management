from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String

from app.database import Base


class NNModel(Base):
    __tablename__ = "nn_models"

    id = Column(Integer, primary_key=True)
    model_name = Column(String, nullable=False, default="ls_nmc")
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="staging")
    artifact_uri = Column(String, nullable=True)
    feature_spec_json = Column(JSON, nullable=True)
    weights_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    promoted_at = Column(DateTime, nullable=True)
