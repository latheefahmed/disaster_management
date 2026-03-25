from sqlalchemy import Column, Integer, String, Float
from app.database import Base


class ScenarioRequest(Base):
    __tablename__ = "scenario_requests"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, nullable=False)

    district_code = Column(String, nullable=False)
    state_code = Column(String, nullable=False)

    resource_id = Column(String, nullable=False)
    time = Column(Integer, nullable=False)
    quantity = Column(Float, nullable=False)
    priority = Column(Float, nullable=False, default=1.0)
    urgency = Column(Float, nullable=False, default=1.0)
    time_index = Column(Float, nullable=False, default=1.0)
