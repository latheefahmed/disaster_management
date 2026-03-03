from sqlalchemy import Column, Integer, String, Float
from app.database import Base


class ScenarioStateStock(Base):
    __tablename__ = "scenario_state_stock"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, nullable=False)

    state_code = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
