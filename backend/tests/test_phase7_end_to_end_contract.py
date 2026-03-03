import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.allocation import Allocation
from app.models.scenario import Scenario
from app.models.scenario_request import ScenarioRequest
from app.models.priority_urgency_event import PriorityUrgencyEvent
from app.models.priority_urgency_model import PriorityUrgencyModel
from app.models.request import ResourceRequest
from app.models.request_prediction import RequestPrediction
from app.models.resource import Resource
from app.models.solver_run import SolverRun
from app.models.state import State
from app.models.district import District
from app.models.user import User
from app.services import priority_urgency_ml_service as pu_service
from app.services.priority_urgency_ml_service import capture_priority_urgency_events, resolve_effective_rank
from app.services.scenario_runner import run_scenario
from app.utils.hashing import hash_password


class Phase7EndToEndContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=cls.engine)

        def override_get_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        db = self.Session()
        try:
            for model in [
                AuditLog,
                PriorityUrgencyEvent,
                RequestPrediction,
                PriorityUrgencyModel,
                ResourceRequest,
                ScenarioRequest,
                Scenario,
                SolverRun,
                Resource,
                District,
                State,
                User,
            ]:
                db.query(model).delete()
            db.commit()

            db.add(State(state_code="10", state_name="State 10"))
            db.add(District(district_code="101", district_name="District 101", state_code="10", demand_mode="baseline_plus_human"))
            db.add(Resource(resource_id="1", canonical_name="water", resource_name="Water", ethical_priority=1.0))
            db.add(User(username="district_user", password_hash=hash_password("pw"), role="district", state_code="10", district_code="101"))
            db.commit()
        finally:
            db.close()

    def _login_header(self):
        res = self.client.post("/auth/login", json={"username": "district_user", "password": "pw"})
        self.assertEqual(res.status_code, 200)
        token = res.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def _seed_models(self, db):
        fcount = len(pu_service.FEATURE_COLUMNS)
        metrics = {
            "model": {
                "weights": [0.0] * fcount,
                "bias": 4.0,
                "mean": [0.0] * fcount,
                "std": [1.0] * fcount,
            },
            "evaluation": {"mae": 0.1, "rmse": 0.1, "samples": 100},
        }
        db.add(PriorityUrgencyModel(model_type="priority", version=1, metrics_json=metrics))
        db.add(PriorityUrgencyModel(model_type="urgency", version=1, metrics_json=metrics))
        db.commit()

    def test_A1_post_without_human_priority_creates_prediction(self):
        db = self.Session()
        try:
            self._seed_models(db)
        finally:
            db.close()

        headers = self._login_header()
        with patch("app.services.request_service._start_live_solver_run", return_value=1), patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True):
            res = self.client.post(
                "/district/request",
                headers=headers,
                json={
                    "resource_id": 1,
                    "time": 1,
                    "quantity": 10,
                    "priority": None,
                    "urgency": None,
                    "confidence": 1.0,
                    "source": "human",
                },
            )

        self.assertEqual(res.status_code, 201)
        payload = res.json()
        self.assertIsNone(payload.get("human_priority"))
        self.assertIsNone(payload.get("human_urgency"))

        db = self.Session()
        try:
            req_id = int(payload["request_id"])
            pred = db.query(RequestPrediction).filter(RequestPrediction.request_id == req_id).first()
            self.assertIsNotNone(pred)
        finally:
            db.close()

    def test_A2_post_with_human_priority_has_no_prediction_row(self):
        headers = self._login_header()
        with patch("app.services.request_service._start_live_solver_run", return_value=2), patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True):
            res = self.client.post(
                "/district/request",
                headers=headers,
                json={
                    "resource_id": 1,
                    "time": 1,
                    "quantity": 10,
                    "priority": 5,
                    "urgency": 5,
                    "confidence": 1.0,
                    "source": "human",
                },
            )

        self.assertEqual(res.status_code, 201)
        req_id = int(res.json()["request_id"])

        db = self.Session()
        try:
            pred = db.query(RequestPrediction).filter(RequestPrediction.request_id == req_id).first()
            self.assertIsNone(pred)
        finally:
            db.close()

    def test_A3_get_requests_includes_human_predicted_confidence(self):
        headers = self._login_header()
        with patch("app.services.request_service._start_live_solver_run", return_value=3), patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True):
            self.client.post(
                "/district/request",
                headers=headers,
                json={
                    "resource_id": 1,
                    "time": 1,
                    "quantity": 10,
                    "priority": None,
                    "urgency": None,
                    "confidence": 1.0,
                    "source": "human",
                },
            )

        rows = self.client.get("/district/requests", headers=headers)
        self.assertEqual(rows.status_code, 200)
        payload = rows.json()
        self.assertTrue(payload)
        self.assertIn("human_priority", payload[0])
        self.assertIn("predicted_priority", payload[0])
        self.assertIn("confidence", payload[0])

    def test_B1_disable_flag_no_predictions(self):
        headers = self._login_header()
        with patch("app.services.request_service._start_live_solver_run", return_value=4), patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", False):
            res = self.client.post(
                "/district/request",
                headers=headers,
                json={
                    "resource_id": 1,
                    "time": 1,
                    "quantity": 10,
                    "priority": None,
                    "urgency": None,
                    "confidence": 1.0,
                    "source": "human",
                },
            )
        self.assertEqual(res.status_code, 201)
        self.assertIsNone(res.json().get("predicted_priority"))

    def test_B2_enable_flag_predictions_appear(self):
        db = self.Session()
        try:
            self._seed_models(db)
        finally:
            db.close()

        headers = self._login_header()
        with patch("app.services.request_service._start_live_solver_run", return_value=5), patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True):
            res = self.client.post(
                "/district/request",
                headers=headers,
                json={
                    "resource_id": 1,
                    "time": 1,
                    "quantity": 10,
                    "priority": None,
                    "urgency": None,
                    "confidence": 1.0,
                    "source": "human",
                },
            )
        self.assertEqual(res.status_code, 201)
        self.assertIsNotNone(res.json().get("predicted_priority"))

    def test_C_solver_source_selection_rules(self):
        self.assertEqual(resolve_effective_rank(5, 2.0, default=1), 5)
        self.assertEqual(resolve_effective_rank(None, 4.4, default=1), 4)
        self.assertEqual(resolve_effective_rank(None, None, default=1), 1)

    def test_D_priority_urgency_events_populated_after_capture(self):
        db = self.Session()
        try:
            run = SolverRun(mode="live", status="completed")
            db.add(run)
            db.flush()
            req = ResourceRequest(
                district_code="101",
                state_code="10",
                resource_id="1",
                time=1,
                quantity=10,
                priority=None,
                urgency=None,
                confidence=1.0,
                source="human",
                status="pending",
                included_in_run=1,
                queued=0,
            )
            db.add(req)
            db.flush()
            db.add(Allocation(
                solver_run_id=run.id,
                request_id=0,
                resource_id="1",
                district_code="101",
                state_code="10",
                time=1,
                allocated_quantity=6,
                is_unmet=False,
            ))
            db.commit()

            baseline_df = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand": 2.0}])
            final_df = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand": 12.0}])

            with patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True):
                rows = capture_priority_urgency_events(
                    db,
                    solver_run_id=run.id,
                    baseline_df=baseline_df,
                    final_df=final_df,
                    request_ids=[req.id],
                )
                db.commit()
            self.assertGreater(rows, 0)
            count = db.query(PriorityUrgencyEvent).count()
            self.assertGreater(count, 0)
        finally:
            db.close()

    def test_E_solver_run_has_priority_urgency_model_ids(self):
        db = self.Session()
        try:
            self._seed_models(db)
            scenario = Scenario(name="E_model_refs")
            db.add(scenario)
            db.commit()

            req = ScenarioRequest(
                scenario_id=scenario.id,
                district_code="101",
                state_code="10",
                resource_id="1",
                time=1,
                quantity=3,
            )
            db.add(req)
            db.commit()
            scenario_id = scenario.id
        finally:
            db.close()

        fake_human_df = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand": 3.0}])
        fake_baseline_df = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand": 2.0}])

        with patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True), \
             patch("app.services.scenario_runner.build_live_demand_snapshot", return_value=fake_human_df), \
             patch("app.services.scenario_runner._load_baseline_demand", return_value=fake_baseline_df), \
             patch("app.services.scenario_runner.run_solver", return_value=None), \
             patch("app.services.scenario_runner.ingest_solver_results", return_value=None), \
             patch("app.services.scenario_runner.capture_demand_learning_events", return_value=0), \
             patch("app.services.scenario_runner.capture_priority_urgency_events_for_scenario", return_value=0), \
             patch("app.services.scenario_runner._write_agent_outputs", return_value=None):
            db = self.Session()
            try:
                run_scenario(db, scenario_id)
            finally:
                db.close()

        db = self.Session()
        try:
            run = db.query(SolverRun).filter(SolverRun.scenario_id == scenario_id).order_by(SolverRun.id.desc()).first()
            self.assertIsNotNone(run.priority_model_id)
            self.assertIsNotNone(run.urgency_model_id)
        finally:
            db.close()

    def test_G_manual_priority_not_overridden_after_rerun(self):
        headers = self._login_header()
        with patch("app.services.request_service._start_live_solver_run", return_value=6), patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True):
            res = self.client.post(
                "/district/request",
                headers=headers,
                json={
                    "resource_id": 1,
                    "time": 1,
                    "quantity": 10,
                    "priority": None,
                    "urgency": None,
                    "confidence": 1.0,
                    "source": "human",
                },
            )

        req_id = int(res.json()["request_id"])
        db = self.Session()
        try:
            req = db.query(ResourceRequest).filter(ResourceRequest.id == req_id).first()
            req.priority = 5
            db.commit()
        finally:
            db.close()

        rows = self.client.get("/district/requests", headers=headers).json()
        row = [r for r in rows if int(r["id"]) == req_id][0]
        self.assertEqual(row["human_priority"], 5)
        self.assertEqual(row["effective_priority"], 5)


if __name__ == "__main__":
    unittest.main()
