from sqlalchemy import Column, String, Float
from app.database import Base

class State(Base):
    __tablename__ = "states"

    state_code = Column(String, primary_key=True)
    state_name = Column(String)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)