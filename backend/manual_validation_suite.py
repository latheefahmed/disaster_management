import json
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base
from app.deps import get_db
from app.utils.hashing import hash_password

from app.models.user import User
from app.models.state import State
from app.models.district import District
from app.models.resource import Resource
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.models.allocation import Allocation
from app.models.pool_transaction import PoolTransaction
from app.models.scenario import Scenario
from app.models.scenario_request import ScenarioRequest
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.scenario_national_stock import ScenarioNationalStock


class ValidationRunner:
    def __init__(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        self.cases = []
        self.tokens = {}

    def teardown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()

    def _record(self, name: str, ok: bool, detail: str = "", severity: str = "green"):
        color = "green" if ok else "red"
        if ok and severity == "yellow":
            color = "yellow"
        self.cases.append(
            {
                "name": name,
                "ok": bool(ok),
                "color": color,
                "detail": detail,
            }
        )

    def _auth_header(self, role: str):
        return {"Authorization": f"Bearer {self.tokens[role]}"}

    def _login(self, username: str, password: str) -> str:
        res = self.client.post("/auth/login", json={"username": username, "password": password})
        if res.status_code != 200:
            raise RuntimeError(f"Login failed for {username}: {res.status_code} {res.text}")
        return res.json()["access_token"]

    def seed(self):
        db = self.Session()
        try:
            for model in [
                ScenarioNationalStock,
                ScenarioStateStock,
                ScenarioRequest,
                Scenario,
                PoolTransaction,
                Allocation,
                SolverRun,
                ResourceRequest,
                Resource,
                District,
                State,
                User,
            ]:
                db.query(model).delete()
            db.commit()

            db.add_all([
                State(state_code="10", state_name="State 10"),
                State(state_code="20", state_name="State 20"),
            ])
            db.add_all([
                District(district_code="101", district_name="District 101", state_code="10", demand_mode="baseline_plus_human"),
                District(district_code="102", district_name="District 102", state_code="10", demand_mode="baseline_plus_human"),
                District(district_code="201", district_name="District 201", state_code="20", demand_mode="baseline_plus_human"),
            ])
            db.add_all([
                Resource(resource_id="water", resource_name="Water", ethical_priority=1.0),
                Resource(resource_id="food", resource_name="Food", ethical_priority=2.0),
                Resource(resource_id="R1", resource_name="food_packets", ethical_priority=2.0),
                Resource(resource_id="R2", resource_name="water_liters", ethical_priority=1.0),
                Resource(resource_id="R10", resource_name="boats", ethical_priority=3.0),
            ])
            db.add_all([
                User(username="district_user", password_hash=hash_password("pw"), role="district", state_code="10", district_code="101"),
                User(username="state_user", password_hash=hash_password("pw"), role="state", state_code="10", district_code=None),
                User(username="national_user", password_hash=hash_password("pw"), role="national", state_code=None, district_code=None),
                User(username="admin_user", password_hash=hash_password("pw"), role="admin", state_code=None, district_code=None),
            ])

            run = SolverRun(mode="live", status="completed")
            db.add(run)
            db.flush()

            db.add_all([
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    resource_id="water",
                    district_code="101",
                    state_code="10",
                    time=1,
                    allocated_quantity=120.0,
                    is_unmet=False,
                    claimed_quantity=0.0,
                    consumed_quantity=0.0,
                    returned_quantity=0.0,
                    status="allocated",
                ),
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    resource_id="food",
                    district_code="101",
                    state_code="10",
                    time=1,
                    allocated_quantity=50.0,
                    is_unmet=True,
                    claimed_quantity=0.0,
                    consumed_quantity=0.0,
                    returned_quantity=0.0,
                    status="unmet",
                ),
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    resource_id="R10",
                    district_code="101",
                    state_code="10",
                    time=1,
                    allocated_quantity=20.0,
                    is_unmet=False,
                    claimed_quantity=0.0,
                    consumed_quantity=0.0,
                    returned_quantity=0.0,
                    status="allocated",
                ),
            ])

            db.add_all([
                ResourceRequest(
                    district_code="101",
                    state_code="10",
                    resource_id="water",
                    time=1,
                    quantity=60.0,
                    priority=1,
                    urgency=1,
                    confidence=1.0,
                    source="human",
                    status="pending",
                ),
                ResourceRequest(
                    district_code="102",
                    state_code="10",
                    resource_id="food",
                    time=1,
                    quantity=30.0,
                    priority=2,
                    urgency=2,
                    confidence=0.9,
                    source="human",
                    status="escalated_national",
                ),
            ])

            db.add(PoolTransaction(
                state_code="10",
                district_code="101",
                resource_id="water",
                time=1,
                quantity_delta=40.0,
                reason="district_return:seed",
                actor_role="district",
                actor_id="101",
            ))
            db.add(PoolTransaction(
                state_code="10",
                district_code="101",
                resource_id="R10",
                time=1,
                quantity_delta=25.0,
                reason="district_return:seed",
                actor_role="district",
                actor_id="101",
            ))

            db.commit()
        finally:
            db.close()

        self.tokens = {
            "district": self._login("district_user", "pw"),
            "state": self._login("state_user", "pw"),
            "national": self._login("national_user", "pw"),
            "admin": self._login("admin_user", "pw"),
        }

    def run_operational_cases(self):
        h_d = self._auth_header("district")
        h_s = self._auth_header("state")
        h_n = self._auth_header("national")

        operational = []

        operational.append(("district me", self.client.get("/district/me", headers=h_d)))
        operational.append(("district demand-mode get", self.client.get("/district/demand-mode", headers=h_d)))
        operational.append(("district demand-mode put human_only", self.client.put("/district/demand-mode", headers=h_d, json={"demand_mode": "human_only"})))
        operational.append(("district demand-mode put ai_human", self.client.put("/district/demand-mode", headers=h_d, json={"demand_mode": "ai_human"})))
        operational.append(("district allocations", self.client.get("/district/allocations", headers=h_d)))
        operational.append(("district unmet", self.client.get("/district/unmet", headers=h_d)))
        operational.append(("district solver-status", self.client.get("/district/solver-status", headers=h_d)))

        operational.append(("district request unknown rejected", self.client.post("/district/request", headers=h_d, json={
            "resource_id": "bad_resource",
            "time": 1,
            "quantity": 10,
            "priority": 1,
            "urgency": 1,
            "confidence": 1.0,
            "source": "human",
        })))

        operational.append(("district request-batch unknown rejected", self.client.post("/district/request-batch", headers=h_d, json={
            "items": [
                {
                    "resource_id": "water",
                    "time": 1,
                    "quantity": 10,
                    "priority": 1,
                    "urgency": 1,
                    "confidence": 1.0,
                    "source": "human",
                },
                {
                    "resource_id": "bad_resource_2",
                    "time": 1,
                    "quantity": 5,
                    "priority": 1,
                    "urgency": 1,
                    "confidence": 1.0,
                    "source": "human",
                },
            ]
        })))

        with patch("app.services.request_service._start_live_solver_run", return_value=77):
            operational.append(("district request alias water_liters accepted", self.client.post("/district/request", headers=h_d, json={
                "resource_id": "water_liters",
                "time": 2,
                "quantity": 20,
                "priority": 1,
                "urgency": 1,
                "confidence": 1.0,
                "source": "human",
            })))
            operational.append(("district request-batch alias food_packets accepted", self.client.post("/district/request-batch", headers=h_d, json={
                "items": [
                    {
                        "resource_id": "food_packets",
                        "time": 2,
                        "quantity": 11,
                        "priority": 1,
                        "urgency": 1,
                        "confidence": 1.0,
                        "source": "human",
                    }
                ]
            })))

        operational.append(("district requests filtered time", self.client.get("/district/requests?time=1", headers=h_d)))
        operational.append(("district claims list", self.client.get("/district/claims", headers=h_d)))
        operational.append(("district consumptions list", self.client.get("/district/consumptions", headers=h_d)))
        operational.append(("district returns list", self.client.get("/district/returns", headers=h_d)))

        operational.append(("district claim", self.client.post("/district/claim", headers=h_d, json={"resource_id": "water", "time": 1, "quantity": 20, "claimed_by": "ops"})))
        operational.append(("district consume", self.client.post("/district/consume", headers=h_d, json={"resource_id": "water", "time": 1, "quantity": 10})))
        operational.append(("district claim reusable", self.client.post("/district/claim", headers=h_d, json={"resource_id": "R10", "time": 1, "quantity": 5, "claimed_by": "ops"})))
        operational.append(("district return", self.client.post("/district/return", headers=h_d, json={"resource_id": "R10", "time": 1, "quantity": 5, "reason": "manual"})))

        operational.append(("state requests", self.client.get("/state/requests", headers=h_s)))
        operational.append(("state allocations", self.client.get("/state/allocations", headers=h_s)))
        operational.append(("state allocation summary", self.client.get("/state/allocations/summary", headers=h_s)))
        operational.append(("state unmet", self.client.get("/state/unmet", headers=h_s)))
        operational.append(("state escalations", self.client.get("/state/escalations", headers=h_s)))
        operational.append(("state pool", self.client.get("/state/pool", headers=h_s)))
        operational.append(("state pool transactions", self.client.get("/state/pool/transactions", headers=h_s)))
        operational.append(("state pool allocate", self.client.post("/state/pool/allocate", headers=h_s, json={
            "resource_id": "R10",
            "time": 1,
            "quantity": 5,
            "target_district": "101",
            "note": "manual rebalance",
        })))

        operational.append(("state escalates request to national", self.client.post("/state/escalations/1", headers=h_s, json={"reason": "overload state pool"})))
        operational.append(("national escalations visible", self.client.get("/national/escalations", headers=h_n)))
        operational.append(("national resolve escalation", self.client.post("/national/escalations/1/resolve", headers=h_n, json={"decision": "partial", "note": "shared from reserve"})))
        operational.append(("national allocations", self.client.get("/national/allocations", headers=h_n)))
        operational.append(("national allocation summary", self.client.get("/national/allocations/summary", headers=h_n)))
        operational.append(("national unmet", self.client.get("/national/unmet", headers=h_n)))

        for idx, (name, res) in enumerate(operational, start=1):
            if name.endswith("unknown rejected"):
                ok = res.status_code == 400 and "Unknown resource_id" in res.text
            else:
                ok = res.status_code == 200
            self._record(f"Operational-{idx:02d}: {name}", ok, f"status={res.status_code}")

    def run_admin_scenario_cases(self):
        h_a = self._auth_header("admin")

        for i in range(1, 21):
            create = self.client.post("/admin/scenarios", headers=h_a, json={"name": f"Scenario-{i}"})
            if create.status_code != 200:
                self._record(f"AdminScenario-{i:02d}: create", False, f"status={create.status_code}")
                continue

            scenario_id = int(create.json()["id"])

            add_batch = self.client.post(
                f"/admin/scenarios/{scenario_id}/add-demand-batch",
                headers=h_a,
                json={
                    "rows": [
                        {
                            "district_code": "101" if i % 2 else "102",
                            "state_code": "10",
                            "resource_id": "water" if i % 3 else "food",
                            "time": (i % 4) + 1,
                            "quantity": float(10 + i),
                        },
                        {
                            "district_code": "201",
                            "state_code": "20",
                            "resource_id": "food",
                            "time": (i % 5) + 1,
                            "quantity": float(6 + i),
                        },
                    ]
                },
            )

            set_state = self.client.post(
                f"/admin/scenarios/{scenario_id}/set-state-stock",
                headers=h_a,
                json={
                    "state_code": "10",
                    "resource_id": "water",
                    "quantity": float(150 + i),
                },
            )

            set_nat = self.client.post(
                f"/admin/scenarios/{scenario_id}/set-national-stock",
                headers=h_a,
                json={
                    "resource_id": "water",
                    "quantity": float(500 + i),
                },
            )

            with patch("app.routers.admin.run_scenario", return_value=None):
                run = self.client.post(f"/admin/scenarios/{scenario_id}/run", headers=h_a, json={})

            runs = self.client.get(f"/admin/scenarios/{scenario_id}/runs", headers=h_a)
            analysis = self.client.get(f"/admin/scenarios/{scenario_id}/analysis", headers=h_a)

            status_ok = all([
                add_batch.status_code == 200,
                set_state.status_code == 200,
                set_nat.status_code == 200,
                run.status_code == 200,
                runs.status_code == 200,
                analysis.status_code == 200,
            ])

            detail = (
                f"batch={add_batch.status_code}, state={set_state.status_code}, national={set_nat.status_code}, "
                f"run={run.status_code}, runs={runs.status_code}, analysis={analysis.status_code}"
            )
            self._record(f"AdminScenario-{i:02d}: full lifecycle", status_ok, detail)

    def build_report(self):
        green = sum(1 for c in self.cases if c["color"] == "green")
        yellow = sum(1 for c in self.cases if c["color"] == "yellow")
        red = sum(1 for c in self.cases if c["color"] == "red")

        total = len(self.cases)
        pass_rate = (green / total) if total else 0.0

        confidence = "low"
        if red == 0 and pass_rate >= 0.98:
            confidence = "golden_candidate"
        elif red <= 2 and pass_rate >= 0.9:
            confidence = "high"
        elif pass_rate >= 0.75:
            confidence = "medium"

        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "totals": {
                "total_cases": total,
                "green": green,
                "yellow": yellow,
                "red": red,
                "pass_rate": round(pass_rate, 4),
            },
            "confidence": confidence,
            "cases": self.cases,
        }


if __name__ == "__main__":
    runner = ValidationRunner()
    try:
        runner.seed()
        runner.run_operational_cases()
        runner.run_admin_scenario_cases()
        report = runner.build_report()

        report_path = "manual_validation_suite_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        totals = report["totals"]
        print(
            f"VALIDATION SUMMARY total={totals['total_cases']} green={totals['green']} yellow={totals['yellow']} red={totals['red']} pass_rate={totals['pass_rate']} confidence={report['confidence']}"
        )
        print(f"Report written: {report_path}")
    finally:
        runner.teardown()
