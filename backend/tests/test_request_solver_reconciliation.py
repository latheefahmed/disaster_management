import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.engine_bridge.ingest import reconcile_requests_from_solver_run
from app.models.allocation import Allocation
from app.models.district import District
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.models.state import State


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    db = Session()
    db.add_all(
        [
            State(state_code="10", state_name="State 10", latitude=12.9, longitude=77.6),
            District(district_code="603", district_name="District 603", state_code="10", demand_mode="baseline_plus_human"),
        ]
    )
    db.commit()

    yield db

    db.close()
    engine.dispose()


def _create_included_request(db, run_id: int, quantity: float = 10.0) -> ResourceRequest:
    req = ResourceRequest(
        district_code="603",
        state_code="10",
        resource_id="R2",
        time=0,
        quantity=float(quantity),
        status="solving",
        lifecycle_state="SENT_TO_SOLVER",
        included_in_run=1,
        queued=0,
        run_id=int(run_id),
    )
    db.add(req)
    db.flush()
    return req


def test_solver_reconciliation_allocated_status(db_session):
    db = db_session
    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    req = _create_included_request(db, run.id, quantity=10.0)
    db.add(
        Allocation(
            solver_run_id=run.id,
            request_id=0,
            resource_id="R2",
            district_code="603",
            state_code="10",
            time=0,
            allocated_quantity=10.0,
            is_unmet=False,
            status="allocated",
        )
    )
    db.commit()

    reconcile_requests_from_solver_run(db, run.id)
    db.commit()
    db.refresh(req)

    assert req.status != "pending"
    assert req.status == "allocated"
    assert float(req.allocated_quantity + req.unmet_quantity) == pytest.approx(float(req.final_demand_quantity))


def test_solver_reconciliation_unmet_status(db_session):
    db = db_session
    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    req = _create_included_request(db, run.id, quantity=12.0)
    db.add(
        Allocation(
            solver_run_id=run.id,
            request_id=0,
            resource_id="R2",
            district_code="603",
            state_code="10",
            time=0,
            allocated_quantity=12.0,
            is_unmet=True,
            status="unmet",
        )
    )
    db.commit()

    reconcile_requests_from_solver_run(db, run.id)
    db.commit()
    db.refresh(req)

    assert req.status == "unmet"
    assert float(req.allocated_quantity) == pytest.approx(0.0)
    assert float(req.unmet_quantity) == pytest.approx(12.0)
    assert float(req.allocated_quantity + req.unmet_quantity) == pytest.approx(float(req.final_demand_quantity))


def test_solver_reconciliation_partial_status(db_session):
    db = db_session
    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    req = _create_included_request(db, run.id, quantity=10.0)
    db.add_all(
        [
            Allocation(
                solver_run_id=run.id,
                request_id=0,
                resource_id="R2",
                district_code="603",
                state_code="10",
                time=0,
                allocated_quantity=6.0,
                is_unmet=False,
                status="allocated",
            ),
            Allocation(
                solver_run_id=run.id,
                request_id=0,
                resource_id="R2",
                district_code="603",
                state_code="10",
                time=0,
                allocated_quantity=4.0,
                is_unmet=True,
                status="unmet",
            ),
        ]
    )
    db.commit()

    reconcile_requests_from_solver_run(db, run.id)
    db.commit()
    db.refresh(req)

    assert req.status == "partial"
    assert float(req.allocated_quantity) == pytest.approx(6.0)
    assert float(req.unmet_quantity) == pytest.approx(4.0)
    assert float(req.allocated_quantity + req.unmet_quantity) == pytest.approx(float(req.final_demand_quantity))
