import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.main import app
from app.models.allocation import Allocation
from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.resource import Resource
from app.models.solver_run import SolverRun
from app.models.state import State
from app.models.user import User
from app.schemas.request import RequestCreate
from app.services import request_service
from app.services.canonical_resources import CANONICAL_RESOURCE_ORDER, CANONICAL_RESOURCE_NAME, CANONICAL_RESOURCE_UNIT
from app.services.kpi_service import compute_district_kpis
from app.utils.hashing import hash_password


def _seed_resources(db):
    for idx, rid in enumerate(CANONICAL_RESOURCE_ORDER, start=1):
        db.add(
            Resource(
                resource_id=rid,
                resource_name=CANONICAL_RESOURCE_NAME[rid],
                canonical_name=CANONICAL_RESOURCE_NAME[rid],
                unit=CANONICAL_RESOURCE_UNIT[rid],
                ethical_priority=float(max(0.1, 2.0 - (idx / 40.0))),
            )
        )


@pytest.fixture()
def test_env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    db = Session()
    db.add_all([
        State(state_code="10", state_name="State 10", latitude=12.9, longitude=77.6),
        State(state_code="11", state_name="State 11", latitude=13.9, longitude=78.6),
        District(district_code="603", district_name="District 603", state_code="10", demand_mode="baseline_plus_human"),
        District(district_code="604", district_name="District 604", state_code="11", demand_mode="baseline_plus_human"),
        User(username="district_user", password_hash=hash_password("pw"), role="district", state_code="10", district_code="603"),
    ])
    _seed_resources(db)
    db.commit()
    db.close()

    yield {"Session": Session, "client": client}

    app.dependency_overrides.clear()
    engine.dispose()


def test_request_reconciliation_time_match(test_env):
    db = test_env["Session"]()
    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    req1 = request_service.ResourceRequest(
        district_code="603", state_code="10", resource_id="R2", time=1, quantity=10,
        status="solving", lifecycle_state="SENT_TO_SOLVER", included_in_run=1, queued=0, run_id=run.id
    )
    req2 = request_service.ResourceRequest(
        district_code="603", state_code="10", resource_id="R2", time=2, quantity=10,
        status="solving", lifecycle_state="SENT_TO_SOLVER", included_in_run=1, queued=0, run_id=run.id
    )
    db.add_all([req1, req2])
    db.flush()

    db.add(Allocation(
        solver_run_id=run.id, request_id=0, resource_id="R2", district_code="603", state_code="10", time=1,
        allocated_quantity=10.0, is_unmet=False, status="allocated"
    ))
    db.add(Allocation(
        solver_run_id=run.id, request_id=0, resource_id="R2", district_code="603", state_code="10", time=2,
        allocated_quantity=10.0, is_unmet=True, status="unmet"
    ))
    db.commit()

    request_service._refresh_request_statuses_for_latest_live_run(db)
    db.refresh(req1)
    db.refresh(req2)

    assert req1.status == "allocated"
    assert req2.status == "unmet"
    db.close()


def test_kpi_correct_aggregation(test_env):
    db = test_env["Session"]()
    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    db.add_all([
        Allocation(solver_run_id=run.id, request_id=0, resource_id="R2", district_code="603", state_code="10", time=0, allocated_quantity=20.0, is_unmet=False, status="allocated"),
        Allocation(solver_run_id=run.id, request_id=0, resource_id="R2", district_code="603", state_code="10", time=1, allocated_quantity=10.0, is_unmet=True, status="unmet"),
        Allocation(solver_run_id=run.id, request_id=0, resource_id="R2", district_code="604", state_code="11", time=0, allocated_quantity=999.0, is_unmet=False, status="allocated"),
        FinalDemand(solver_run_id=run.id, district_code="603", state_code="10", resource_id="R2", time=0, demand_quantity=20.0),
        FinalDemand(solver_run_id=run.id, district_code="603", state_code="10", resource_id="R2", time=1, demand_quantity=10.0),
        FinalDemand(solver_run_id=run.id, district_code="604", state_code="11", resource_id="R2", time=0, demand_quantity=999.0),
    ])
    db.commit()

    kpi = compute_district_kpis(db, "603")
    assert float(kpi["allocated"]) == pytest.approx(20.0)
    assert float(kpi["unmet"]) == pytest.approx(10.0)
    assert float(kpi["final_demand"]) == pytest.approx(30.0)
    assert float(kpi["coverage"]) == pytest.approx(20.0 / 30.0)
    db.close()


def test_duplicate_prevention(test_env, monkeypatch):
    db = test_env["Session"]()
    monkeypatch.setattr(request_service, "_start_live_solver_run", lambda _db: 1)

    user = {"district_code": "603", "state_code": "10"}
    payload = RequestCreate(resource_id="R2", time=1, quantity=5, priority=1, urgency=1, confidence=1.0, source="human")

    request_service.create_request(db, user, payload)
    payload2 = RequestCreate(resource_id="R2", time=1, quantity=7, priority=1, urgency=1, confidence=1.0, source="human")
    request_service.create_request(db, user, payload2)

    rows = db.query(request_service.ResourceRequest).filter(
        request_service.ResourceRequest.district_code == "603",
        request_service.ResourceRequest.resource_id == "R2",
        request_service.ResourceRequest.time == 1,
        request_service.ResourceRequest.run_id == 0,
    ).all()
    assert len(rows) == 1
    assert float(rows[0].quantity) == pytest.approx(12.0)
    db.close()


def test_solver_conservation(test_env):
    db = test_env["Session"]()
    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    db.add_all([
        Allocation(solver_run_id=run.id, request_id=0, resource_id="R2", district_code="603", state_code="10", time=0, allocated_quantity=12.0, is_unmet=False, status="allocated"),
        Allocation(solver_run_id=run.id, request_id=0, resource_id="R2", district_code="603", state_code="10", time=0, allocated_quantity=3.0, is_unmet=True, status="unmet"),
        FinalDemand(solver_run_id=run.id, district_code="603", state_code="10", resource_id="R2", time=0, demand_quantity=15.0),
    ])
    db.commit()

    kpi = compute_district_kpis(db, "603")
    assert abs((float(kpi["allocated"]) + float(kpi["unmet"])) - float(kpi["final_demand"])) < 1e-6
    db.close()


def test_month_scale_allocation(test_env):
    frame = request_service.pd.DataFrame([
        {"district_code": "603", "resource_id": "R2", "time": 1, "demand": 5.0, "demand_mode": "baseline_plus_human", "source_mix": "human"}
    ])
    expanded = request_service._expand_month_horizon(frame, ["603"])

    assert int(expanded["time"].min()) == 0
    assert int(expanded["time"].max()) == 29
    assert len(expanded) == len(CANONICAL_RESOURCE_ORDER) * 30

    row = expanded[(expanded["resource_id"] == "R2") & (expanded["time"] == 1)]
    assert float(row.iloc[0]["demand"]) == pytest.approx(5.0)
