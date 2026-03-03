import time
from sqlalchemy import func

from app.database import SessionLocal
from app.models.district import District
from app.models.solver_run import SolverRun
from app.models.final_demand import FinalDemand
from app.models.allocation import Allocation
from app.services.request_service import create_request_batch


def wait_for(run_id: int, timeout: int = 240):
    start = time.time()
    while time.time() - start < timeout:
        db = SessionLocal()
        try:
            row = db.query(SolverRun).filter(SolverRun.id == run_id).first()
            if row is not None and row.status in {"completed", "failed"}:
                return row.status
        finally:
            db.close()
        time.sleep(1)
    db = SessionLocal()
    try:
        row = db.query(SolverRun).filter(SolverRun.id == run_id).first()
        return row.status if row else "missing"
    finally:
        db.close()


def main():
    db = SessionLocal()
    try:
        district = db.query(District).filter(District.district_code == "603").first()
        if district is None:
            raise RuntimeError("District 603 not found")

        mode_before = str(district.demand_mode or "baseline_plus_human")
        district.demand_mode = "human_only"
        db.commit()

        out = create_request_batch(
            db,
            {"district_code": "603", "state_code": str(district.state_code)},
            [
                {
                    "resource_id": "R1",
                    "time": 0,
                    "quantity": 10,
                    "priority": 1,
                    "urgency": 1,
                    "confidence": 1.0,
                    "source": "human",
                }
            ],
        )
        run_id = int(out["solver_run_id"])

        district.demand_mode = mode_before
        db.commit()
    finally:
        db.close()

    status = wait_for(run_id)

    db = SessionLocal()
    try:
        final_count = int(db.query(func.count(FinalDemand.id)).filter(FinalDemand.solver_run_id == run_id).scalar() or 0)
        alloc_count = int(db.query(func.count(Allocation.id)).filter(Allocation.solver_run_id == run_id).scalar() or 0)
        print("LIVE_SMOKE", {"run_id": run_id, "status": status, "final_demands": final_count, "allocations": alloc_count})
    finally:
        db.close()


if __name__ == "__main__":
    main()
