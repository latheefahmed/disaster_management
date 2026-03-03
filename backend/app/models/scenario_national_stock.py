from sqlalchemy import Column, Integer, String, Float
from app.database import Base


class ScenarioNationalStock(Base):
    __tablename__ = "scenario_national_stock"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, nullable=False)

    resource_id = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
