from pydantic import BaseModel


class StockRefillCreate(BaseModel):
    resource_id: str
    quantity: float
    note: str | None = None
