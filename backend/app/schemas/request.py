from pydantic import BaseModel
from uuid import UUID


class RequestCreate(BaseModel):
    resource_id: int | UUID | str
    time: int
    quantity: float
    priority: int | None = None
    urgency: int | None = None
    confidence: float = 1.0
    source: str = "human"


class RequestOut(BaseModel):
    id: int
    district_code: str
    state_code: str
    resource_id: str
    time: int
    quantity: float
    priority: int | None
    urgency: int | None
    confidence: float
    source: str
    status: str

    class Config:
        from_attributes = True
