import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.main import app
from app.models.district import District
from app.models.resource import Resource
from app.models.state import State
from app.models.user import User
from app.services.canonical_resources import CANONICAL_RESOURCE_ORDER, CANONICAL_RESOURCE_NAME, CANONICAL_RESOURCE_UNIT
from app.utils.hashing import hash_password
import app.services.kpi_service as kpi_service


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
def test_env(monkeypatch):
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
    _seed_resources(db)
    db.commit()
    db.close()

    monkeypatch.setattr(kpi_service, "_load_district_stock_csv", lambda: {})
    monkeypatch.setattr(kpi_service, "_load_state_stock_csv", lambda: {})
    monkeypatch.setattr(kpi_service, "_load_national_stock_csv", lambda: {})

    yield {"client": client}

    app.dependency_overrides.clear()
    engine.dispose()


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def _find(rows: list[dict], rid: str):
    return next(r for r in rows if r["resource_id"] == rid)


def test_district_refill_updates_district_stock(test_env):
    client = test_env["client"]
    token = _login(client, "district_user", "pw")

    before = client.get("/district/stock", headers={"Authorization": f"Bearer {token}"}).json()
    assert float(_find(before, "R10")["district_stock"]) == pytest.approx(0.0)

    refill = client.post(
        "/district/stock/refill",
        headers={"Authorization": f"Bearer {token}"},
        json={"resource_id": "R10", "quantity": 25, "note": "test_refill"},
    )
    assert refill.status_code == 200

    after = client.get("/district/stock", headers={"Authorization": f"Bearer {token}"}).json()
    assert float(_find(after, "R10")["district_stock"]) == pytest.approx(25.0)


def test_state_and_national_refill_update_visible_stock(test_env):
    client = test_env["client"]
    state_token = _login(client, "state_user", "pw")
    national_token = _login(client, "national_user", "pw")

    state_refill = client.post(
        "/state/stock/refill",
        headers={"Authorization": f"Bearer {state_token}"},
        json={"resource_id": "R6", "quantity": 100, "note": "state_refill"},
    )
    assert state_refill.status_code == 200

    national_refill = client.post(
        "/national/stock/refill",
        headers={"Authorization": f"Bearer {national_token}"},
        json={"resource_id": "R6", "quantity": 300, "note": "national_refill"},
    )
    assert national_refill.status_code == 200

    state_rows = client.get("/state/stock", headers={"Authorization": f"Bearer {state_token}"}).json()
    national_rows = client.get("/national/stock", headers={"Authorization": f"Bearer {national_token}"}).json()

    assert float(_find(state_rows, "R6")["state_stock"]) == pytest.approx(100.0)
    assert float(_find(national_rows, "R6")["national_stock"]) == pytest.approx(300.0)
