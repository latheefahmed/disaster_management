from sqlalchemy import Column, String, Float, Boolean
from app.database import Base


class CanonicalResource(Base):
    __tablename__ = "canonical_resources"

    canonical_id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    unit = Column(String, nullable=False)
    category = Column(String, nullable=False)
    class_type = Column(String, nullable=False)
    can_consume = Column(Boolean, nullable=False, default=False)
    can_return = Column(Boolean, nullable=False, default=False)
    count_type = Column(String, nullable=False)
    max_reasonable_quantity = Column(Float, nullable=False)
