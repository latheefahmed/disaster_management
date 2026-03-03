from pydantic import BaseModel


class KPIOut(BaseModel):
    solver_run_id: int | None
    allocated: float
    unmet: float
    final_demand: float
    coverage: float
