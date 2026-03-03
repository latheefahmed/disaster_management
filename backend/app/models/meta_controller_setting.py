from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.database import Base


class MetaControllerSetting(Base):
    __tablename__ = "meta_controller_settings"

    id = Column(Integer, primary_key=True)
    mode = Column(String, nullable=False, default="shadow")
    influence_pct = Column(Float, nullable=False, default=0.2)
    nn_enabled = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow)
