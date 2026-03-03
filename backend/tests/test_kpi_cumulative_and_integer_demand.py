import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.allocation import Allocation
from app.models.final_demand import FinalDemand
from app.models.solver_run import SolverRun
from app.services.final_demand_service import normalize_final_demand_frame
from app.services.kpi_service import compute_district_kpis


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    db = Session()
    yield db
    db.close()
    engine.dispose()


def test_normalize_final_demand_frame_enforces_integer_demands():
    frame = pd.DataFrame(
        [
            {"district_code": "603", "resource_id": "R38", "time": 0, "demand": 0.12},
            {"district_code": "603", "resource_id": "R38", "time": 1, "demand": 1.01},
            {"district_code": "603", "resource_id": "R2", "time": 2, "demand": 0.49},
        ]
    )

    out = normalize_final_demand_frame(frame)
    demand_map = {(str(r.district_code), str(r.resource_id), int(r.time)): float(r.demand) for r in out.itertuples(index=False)}

    assert demand_map[("603", "R38", 0)] == pytest.approx(1.0)
    assert demand_map[("603", "R38", 1)] == pytest.approx(2.0)
    assert demand_map[("603", "R2", 2)] == pytest.approx(1.0)


def test_compute_district_kpis_is_cumulative_over_completed_runs(db_session):
    db = db_session

    run1 = SolverRun(mode="live", status="completed")
    run2 = SolverRun(mode="live", status="completed")
    db.add_all([run1, run2])
    db.commit()
    db.refresh(run1)
    db.refresh(run2)

    db.add_all(
        [
            Allocation(solver_run_id=run1.id, request_id=0, resource_id="R2", district_code="603", state_code="10", time=0, allocated_quantity=6.0, is_unmet=False, status="allocated"),
            Allocation(solver_run_id=run1.id, request_id=0, resource_id="R2", district_code="603", state_code="10", time=0, allocated_quantity=2.0, is_unmet=True, status="unmet"),
            FinalDemand(solver_run_id=run1.id, district_code="603", state_code="10", resource_id="R2", time=0, demand_quantity=8.0),
            Allocation(solver_run_id=run2.id, request_id=0, resource_id="R2", district_code="603", state_code="10", time=1, allocated_quantity=4.0, is_unmet=False, status="allocated"),
            Allocation(solver_run_id=run2.id, request_id=0, resource_id="R2", district_code="603", state_code="10", time=1, allocated_quantity=1.0, is_unmet=True, status="unmet"),
            FinalDemand(solver_run_id=run2.id, district_code="603", state_code="10", resource_id="R2", time=1, demand_quantity=5.0),
        ]
    )
    db.commit()

    kpi = compute_district_kpis(db, "603")

    assert int(kpi["solver_run_id"]) == int(run2.id)
    assert float(kpi["allocated"]) == pytest.approx(10.0)
    assert float(kpi["unmet"]) == pytest.approx(3.0)
    assert float(kpi["final_demand"]) == pytest.approx(13.0)
    assert float(kpi["coverage"]) == pytest.approx(10.0 / 13.0)
