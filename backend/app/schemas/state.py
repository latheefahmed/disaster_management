from pydantic import BaseModel


class NationalPoolAllocateCreate(BaseModel):
	state_code: str
	resource_id: str
	time: int
	quantity: float
	target_district: str | None = None
	note: str | None = None
