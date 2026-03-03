from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from app.database import Base


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(String, default="created")   # created | running | completed
    created_at = Column(DateTime, default=datetime.utcnow)
