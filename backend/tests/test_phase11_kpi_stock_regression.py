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
from app.models.inventory_snapshot import InventorySnapshot
from app.models.scenario import Scenario
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.resource import Resource
from app.models.solver_run import SolverRun
from app.models.state import State
from app.models.user import User
from app.models.pool_transaction import PoolTransaction
import app.services.kpi_service as kpi_service
from app.services.kpi_service import compute_district_kpis
from app.services.canonical_resources import (
    CANONICAL_RESOURCE_ORDER,
    CANONICAL_RESOURCE_NAME,
    CANONICAL_RESOURCE_UNIT,
)
from app.utils.hashing import hash_password


def _seed_canonical_resources(db):
    for idx, rid in enumerate(CANONICAL_RESOURCE_ORDER, start=1):
        name = CANONICAL_RESOURCE_NAME[rid]
        unit = CANONICAL_RESOURCE_UNIT[rid]
        priority = float(max(0.1, 2.0 - (idx / 40.0)))
        db.add(Resource(resource_id=rid, resource_name=name, canonical_name=name, unit=unit, ethical_priority=priority))


@pytest.fixture()
def test_env():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
        District(district_code="603", district_name="District 603", state_code="10", demand_mode="baseline_plus_human"),
        User(username="district_user", password_hash=hash_password("pw"), role="district", state_code="10", district_code="603"),
        User(username="state_user", password_hash=hash_password("pw"), role="state", state_code="10", district_code=None),
        User(username="national_user", password_hash=hash_password("pw"), role="national", state_code=None, district_code=None),
    ])
    _seed_canonical_resources(db)
    db.commit()
    db.close()

    yield {"engine": engine, "Session": Session, "client": client}

    app.dependency_overrides.clear()
    engine.dispose()


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_kpi_conservation(test_env):
    db = test_env["Session"]()
    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    db.add_all([
        Allocation(
            solver_run_id=run.id,
            request_id=0,
            resource_id="R2",
            district_code="603",
            state_code="10",
            time=1,
            allocated_quantity=120.0,
            is_unmet=False,
            status="allocated",
        ),
        Allocation(
            solver_run_id=run.id,
            request_id=0,
            resource_id="R1",
            district_code="603",
            state_code="10",
            time=1,
            allocated_quantity=30.0,
            is_unmet=True,
            status="unmet",
        ),
    ])
    db.commit()

    kpi = compute_district_kpis(db, "603")
    assert abs((kpi["allocated"] + kpi["unmet"]) - kpi["final_demand"]) < 1e-6
    db.close()


def test_kpis_not_zero_when_allocations_exist(test_env):
    db = test_env["Session"]()
    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    db.add(
        Allocation(
            solver_run_id=run.id,
            request_id=0,
            resource_id="R2",
            district_code="603",
            state_code="10",
            time=1,
            allocated_quantity=55.0,
            is_unmet=False,
            status="allocated",
        )
    )
    db.commit()

    token = _login(test_env["client"], "district_user", "pw")
    res = test_env["client"].get("/district/kpis", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    payload = res.json()
    assert float(payload["allocated"]) > 0.0
    db.close()


def test_stock_endpoint_accuracy(test_env):
    db = test_env["Session"]()

    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    scenario = Scenario(name="phase11-stock")
    db.add(scenario)
    db.commit()
    db.refresh(scenario)

    rows = []
    for rid in CANONICAL_RESOURCE_ORDER:
        rows.append(
            InventorySnapshot(
                solver_run_id=run.id,
                district_code="603",
                resource_id=rid,
                time=1,
                quantity=25.0 if rid == "R2" else 0.0,
            )
        )
        rows.append(
            ScenarioStateStock(
                scenario_id=scenario.id,
                state_code="10",
                resource_id=rid,
                quantity=40.0 if rid == "R2" else 0.0,
            )
        )
        rows.append(
            ScenarioNationalStock(
                scenario_id=scenario.id,
                resource_id=rid,
                quantity=90.0 if rid == "R2" else 0.0,
            )
        )
    db.add_all(rows)
    db.commit()
    db.close()

    district_token = _login(test_env["client"], "district_user", "pw")
    district_res = test_env["client"].get("/district/stock", headers={"Authorization": f"Bearer {district_token}"})
    assert district_res.status_code == 200
    district_rows = district_res.json()
    assert len(district_rows) == len(CANONICAL_RESOURCE_ORDER)
    water = next(r for r in district_rows if r["resource_id"] == "R2")
    assert float(water["district_stock"]) == pytest.approx(25.0)
    assert float(water["state_stock"]) == pytest.approx(40.0)
    assert float(water["national_stock"]) == pytest.approx(90.0)
    assert float(water["available_stock"]) == pytest.approx(155.0)


def test_district_stock_includes_state_pool_returns(test_env):
    db = test_env["Session"]()

    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    scenario = Scenario(name="pool-return-stock")
    db.add(scenario)
    db.commit()
    db.refresh(scenario)

    db.add(
        ScenarioStateStock(
            scenario_id=scenario.id,
            state_code="10",
            resource_id="R37",
            quantity=28.0,
        )
    )
    db.commit()

    token = _login(test_env["client"], "district_user", "pw")
    before_res = test_env["client"].get("/district/stock", headers={"Authorization": f"Bearer {token}"})
    assert before_res.status_code == 200
    before_row = next(r for r in before_res.json() if r["resource_id"] == "R37")
    assert float(before_row["state_stock"]) == pytest.approx(28.0)

    db.add(
        PoolTransaction(
            state_code="10",
            district_code="603",
            resource_id="R37",
            time=1,
            quantity_delta=7.0,
            reason="district_return:manual",
            actor_role="district",
            actor_id="603",
        )
    )
    db.commit()
    db.close()

    after_res = test_env["client"].get("/district/stock", headers={"Authorization": f"Bearer {token}"})
    assert after_res.status_code == 200
    after_row = next(r for r in after_res.json() if r["resource_id"] == "R37")
    assert float(after_row["state_stock"]) == pytest.approx(35.0)
    assert float(after_row["available_stock"]) >= float(before_row["available_stock"]) + 7.0 - 1e-6


def test_district_stock_includes_national_pool_returns(test_env):
    db = test_env["Session"]()

    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()

    scenario = Scenario(name="national-pool-return-stock")
    db.add(scenario)
    db.commit()
    db.refresh(scenario)

    db.add(
        ScenarioNationalStock(
            scenario_id=scenario.id,
            resource_id="R37",
            quantity=28.0,
        )
    )
    db.commit()

    token = _login(test_env["client"], "district_user", "pw")
    before_res = test_env["client"].get("/district/stock", headers={"Authorization": f"Bearer {token}"})
    assert before_res.status_code == 200
    before_row = next(r for r in before_res.json() if r["resource_id"] == "R37")
    assert float(before_row["national_stock"]) == pytest.approx(28.0)

    db.add(
        PoolTransaction(
            state_code="NATIONAL",
            district_code="603",
            resource_id="R37",
            time=1,
            quantity_delta=6.0,
            reason="district_return_to_origin:manual",
            actor_role="district",
            actor_id="603",
        )
    )
    db.commit()
    db.close()

    after_res = test_env["client"].get("/district/stock", headers={"Authorization": f"Bearer {token}"})
    assert after_res.status_code == 200
    after_row = next(r for r in after_res.json() if r["resource_id"] == "R37")
    assert float(after_row["national_stock"]) == pytest.approx(34.0)
    assert float(after_row["available_stock"]) >= float(before_row["available_stock"]) + 6.0 - 1e-6


def test_kpi_scopes_to_latest_completed_run(test_env):
    db = test_env["Session"]()

    old_run = SolverRun(mode="live", status="completed")
    latest_run = SolverRun(mode="live", status="completed")
    db.add_all([old_run, latest_run])
    db.commit()
    db.refresh(old_run)
    db.refresh(latest_run)

    db.add_all([
        Allocation(
            solver_run_id=old_run.id,
            request_id=0,
            resource_id="R2",
            district_code="603",
            state_code="10",
            time=1,
            allocated_quantity=10.0,
            is_unmet=False,
            status="allocated",
        ),
        Allocation(
            solver_run_id=latest_run.id,
            request_id=0,
            resource_id="R2",
            district_code="603",
            state_code="10",
            time=1,
            allocated_quantity=77.0,
            is_unmet=False,
            status="allocated",
        ),
    ])
    db.commit()
    latest_run_id = int(latest_run.id)
    db.close()

    token = _login(test_env["client"], "district_user", "pw")
    res = test_env["client"].get("/district/kpis", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    payload = res.json()
    assert int(payload["solver_run_id"]) == latest_run_id
    assert float(payload["allocated"]) == pytest.approx(87.0)


def test_role_specific_kpi_aggregation(test_env):
    db = test_env["Session"]()
    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    db.add_all([
        Allocation(
            solver_run_id=run.id,
            request_id=0,
            resource_id="R2",
            district_code="603",
            state_code="10",
            time=1,
            allocated_quantity=30.0,
            is_unmet=False,
            status="allocated",
        ),
        Allocation(
            solver_run_id=run.id,
            request_id=0,
            resource_id="R1",
            district_code="999",
            state_code="99",
            time=1,
            allocated_quantity=70.0,
            is_unmet=False,
            status="allocated",
        ),
    ])
    db.commit()
    db.close()

    state_token = _login(test_env["client"], "state_user", "pw")
    district_token = _login(test_env["client"], "district_user", "pw")
    national_token = _login(test_env["client"], "national_user", "pw")

    district_res = test_env["client"].get("/district/kpis", headers={"Authorization": f"Bearer {district_token}"})
    state_res = test_env["client"].get("/state/kpis", headers={"Authorization": f"Bearer {state_token}"})
    national_res = test_env["client"].get("/national/kpis", headers={"Authorization": f"Bearer {national_token}"})

    assert district_res.status_code == 200
    assert state_res.status_code == 200
    assert national_res.status_code == 200

    district_alloc = float(district_res.json()["allocated"])
    state_alloc = float(state_res.json()["allocated"])
    national_alloc = float(national_res.json()["allocated"])

    assert district_alloc == pytest.approx(30.0)
    assert state_alloc == pytest.approx(30.0)
    assert national_alloc == pytest.approx(100.0)


def test_resource_canonicality(test_env):
    token = _login(test_env["client"], "district_user", "pw")
    res = test_env["client"].get("/metadata/resources", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    ids = [r["resource_id"] for r in res.json()]
    assert ids == CANONICAL_RESOURCE_ORDER


def test_inventory_returns_all_resources(test_env):
    token = _login(test_env["client"], "district_user", "pw")
    res = test_env["client"].get("/district/stock", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == len(CANONICAL_RESOURCE_ORDER)
    assert {r["resource_id"] for r in rows} == set(CANONICAL_RESOURCE_ORDER)


def test_stock_csv_fallback_when_db_stock_sparse(test_env, monkeypatch):
    db = test_env["Session"]()
    run = SolverRun(mode="live", status="completed")
    scenario = Scenario(name="sparse-stock")
    db.add_all([run, scenario])
    db.commit()
    db.close()

    monkeypatch.setattr(kpi_service, "_load_district_stock_csv", lambda: {("603", "R2"): 120.0})
    monkeypatch.setattr(kpi_service, "_load_state_stock_csv", lambda: {("10", "R2"): 340.0})
    monkeypatch.setattr(kpi_service, "_load_national_stock_csv", lambda: {"R2": 560.0})

    token = _login(test_env["client"], "district_user", "pw")
    res = test_env["client"].get("/district/stock", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == len(CANONICAL_RESOURCE_ORDER)

    row = next(r for r in rows if r["resource_id"] == "R2")
    assert float(row["district_stock"]) == pytest.approx(120.0)
    assert float(row["state_stock"]) == pytest.approx(340.0)
    assert float(row["national_stock"]) == pytest.approx(560.0)
    assert float(row["available_stock"]) == pytest.approx(1020.0)


def test_invalid_resource_rejected(test_env):
    token = _login(test_env["client"], "district_user", "pw")
    res = test_env["client"].post(
        "/district/request",
        headers={"Authorization": f"Bearer {token}"},
        json={"resource_id": "T99", "time": 1, "quantity": 1, "priority": 1, "urgency": 1, "confidence": 1.0, "source": "human"},
    )
    assert res.status_code == 400


def test_claim_fsm(test_env):
    db = test_env["Session"]()
    run = SolverRun(mode="live", status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)

    db.add(
        Allocation(
            solver_run_id=run.id,
            request_id=0,
            resource_id="R10",
            district_code="603",
            state_code="10",
            time=2,
            allocated_quantity=8.0,
            is_unmet=False,
            status="allocated",
        )
    )
    db.commit()
    db.close()

    token = _login(test_env["client"], "district_user", "pw")

    claim = test_env["client"].post(
        "/district/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"resource_id": "R10", "time": 2, "quantity": 8, "claimed_by": "ops"},
    )
    assert claim.status_code == 200

    ret = test_env["client"].post(
        "/district/return",
        headers={"Authorization": f"Bearer {token}"},
        json={"resource_id": "R10", "time": 2, "quantity": 8, "reason": "manual"},
    )
    assert ret.status_code == 200
    assert ret.json()["snapshot"]["status"] in {"RETURNED", "CLAIMED"}
