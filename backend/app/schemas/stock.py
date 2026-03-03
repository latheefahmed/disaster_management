from pydantic import BaseModel


class StockRowOut(BaseModel):
    resource_id: str
    district_stock: float
    state_stock: float
    national_stock: float
    in_transit: float
    available_stock: float
