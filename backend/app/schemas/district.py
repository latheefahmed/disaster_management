from pydantic import BaseModel
from typing import Literal


class DistrictOut(BaseModel):
    district_code: str
    district_name: str | None
    state_code: str | None
    demand_mode: str

    class Config:
        from_attributes = True


class DemandModeUpdate(BaseModel):
    demand_mode: Literal[
        "baseline_plus_human",
        "human_only",
        "baseline_only",
        "ai_human",
        "only_human",
        "ai_only",
    ]


class ClaimCreate(BaseModel):
    resource_id: str
    time: int
    quantity: float
    claimed_by: str | None = "district_manager"
    solver_run_id: int | None = None


class ConsumptionCreate(BaseModel):
    resource_id: str
    time: int
    quantity: float
    solver_run_id: int | None = None


class ReturnCreate(BaseModel):
    resource_id: str
    time: int
    quantity: float
    reason: Literal["manual", "expiry"]
    solver_run_id: int | None = None
    allocation_source_scope: str | None = None
    allocation_source_code: str | None = None


class PoolAllocateCreate(BaseModel):
    resource_id: str
    time: int
    quantity: float
    target_district: str | None = None
    note: str | None = None
