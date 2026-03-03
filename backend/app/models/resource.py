from sqlalchemy import Column, String, Float
from app.database import Base

class Resource(Base):
    __tablename__ = "resources"

    resource_id = Column(String, primary_key=True)
    resource_name = Column(String)
    unit = Column(String)
    ethical_priority = Column(Float)
    canonical_name = Column(String, unique=True)