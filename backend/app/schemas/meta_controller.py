from pydantic import BaseModel


class ToggleNNRequest(BaseModel):
    enabled: bool


class PromoteModelRequest(BaseModel):
    model_version: int


class RollbackModelRequest(BaseModel):
    target_version: int
