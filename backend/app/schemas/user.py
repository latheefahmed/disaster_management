from pydantic import BaseModel


class UserOut(BaseModel):
    username: str
    role: str
    state_code: str | None
    district_code: str | None
