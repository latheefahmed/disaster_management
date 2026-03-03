from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String

from app.database import Base


class NNFeatureCache(Base):
    __tablename__ = "nn_feature_cache"

    id = Column(Integer, primary_key=True)
    solver_run_id = Column(Integer, nullable=True)
    district_code = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)
    raw_features_json = Column(JSON, nullable=False)
    norm_features_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
