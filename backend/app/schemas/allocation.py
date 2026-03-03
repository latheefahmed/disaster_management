from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AllocationOut(BaseModel):
    id: int
    solver_run_id: int
    request_id: Optional[int] = None
    source_request_id: Optional[int] = None
    source_request_created_at: Optional[datetime] = None
    source_batch_id: Optional[int] = None
    supply_level: str = "district"
    allocation_source_scope: Optional[str] = None
    allocation_source_code: Optional[str] = None
    resource_id: str
    district_code: str
    state_code: str
    origin_state_code: Optional[str] = None
    origin_district_code: Optional[str] = None
    time: int
    allocated_quantity: float
    implied_delay_hours: Optional[float] = None
    receipt_confirmed: bool = False
    receipt_time: Optional[datetime] = None
    claimed_quantity: float = 0.0
    consumed_quantity: float = 0.0
    returned_quantity: float = 0.0
    status: str = "allocated"

    class Config:
        from_attributes = True
