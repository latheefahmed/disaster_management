import math
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.main import app
from app.models.adaptive_parameter import AdaptiveParameter
from app.models.district import District
from app.models.meta_controller_setting import MetaControllerSetting
from app.models.nn_model import NNModel
from app.models.neural_incident_log import NeuralIncidentLog
from app.models.solver_run import SolverRun
from app.models.state import State
from app.models.user import User
from app.services.neural_controller import get_params
from app.utils.hashing import hash_password


class Phase10NeuralScaffoldTests(unittest.TestCase):
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
                AdaptiveParameter,
                NeuralIncidentLog,
                NNModel,
                MetaControllerSetting,
                SolverRun,
                District,
                State,
                User,
            ]:
                db.query(model).delete()
            db.commit()

            db.add(State(state_code="10", state_name="State 10", latitude=12.9, longitude=77.6))
            db.add(District(district_code="101", district_name="District 101", state_code="10", demand_mode="baseline_plus_human"))
            db.add(User(username="admin_user", password_hash=hash_password("pw"), role="admin", state_code=None, district_code=None))
            db.add(SolverRun(mode="live", status="completed"))
            db.commit()
        finally:
            db.close()

        self.admin_token = self._login("admin_user", "pw")

    def _login(self, username: str, password: str) -> str:
        res = self.client.post("/auth/login", json={"username": username, "password": password})
        self.assertEqual(res.status_code, 200)
        return str(res.json()["access_token"])

    def _auth(self):
        return {"Authorization": f"Bearer {self.admin_token}"}

    def test_neural_disabled_uses_fallback(self):
        db = self.Session()
        try:
            with patch("app.services.neural_controller.ENABLE_NN_META_CONTROLLER", False):
                out = get_params(db, solver_run_id=1)
            self.assertEqual(str(out["source"]), "fallback")
        finally:
            db.close()

    def test_neural_enabled_uses_prod_model(self):
        db = self.Session()
        try:
            db.add(MetaControllerSetting(id=1, mode="blended", influence_pct=0.2, nn_enabled=1))
            db.add(NNModel(model_name="ls_nmc", version=1, status="prod", weights_json={
                "alpha": 0.4,
                "beta": 0.6,
                "gamma": 1.2,
                "p_mult": 1.1,
                "u_mult": 1.05,
            }))
            db.commit()

            with patch("app.services.neural_controller.ENABLE_NN_META_CONTROLLER", True):
                with patch("app.services.neural_controller.infer_raw_params", return_value={
                    "alpha": 1.2,
                    "beta": 1.6,
                    "gamma": 1.5,
                    "p_mult": 1.4,
                    "u_mult": 1.2,
                    "model_version": 1,
                }):
                    out = get_params(db, solver_run_id=1)

            self.assertEqual(str(out["source"]), "neural_blend")
            self.assertTrue(0.2 <= float(out["alpha"]) <= 0.8)
            self.assertTrue(0.2 <= float(out["beta"]) <= 0.8)
        finally:
            db.close()

    def test_neural_nan_triggers_fallback(self):
        db = self.Session()
        try:
            db.add(MetaControllerSetting(id=1, mode="blended", influence_pct=0.2, nn_enabled=1))
            db.add(NNModel(model_name="ls_nmc", version=1, status="prod", weights_json={
                "alpha": 0.4,
                "beta": 0.6,
                "gamma": 1.2,
                "p_mult": 1.1,
                "u_mult": 1.05,
            }))
            db.commit()

            with patch("app.services.neural_controller.ENABLE_NN_META_CONTROLLER", True):
                with patch("app.services.neural_controller.infer_raw_params", return_value={
                    "alpha": math.nan,
                    "beta": 0.5,
                    "gamma": 1.0,
                    "p_mult": 1.0,
                    "u_mult": 1.0,
                    "model_version": 1,
                }):
                    out = get_params(db, solver_run_id=1)

            self.assertEqual(str(out["source"]), "fallback")
            incident = db.query(NeuralIncidentLog).order_by(NeuralIncidentLog.id.desc()).first()
            self.assertIsNotNone(incident)
        finally:
            db.close()

    def test_fallback_flag_persisted_when_neural_fails(self):
        db = self.Session()
        try:
            with patch("app.services.neural_controller.ENABLE_NN_META_CONTROLLER", True):
                out = get_params(db, solver_run_id=1)
            self.assertEqual(str(out["source"]), "fallback")
            row = db.query(AdaptiveParameter).order_by(AdaptiveParameter.id.desc()).first()
            self.assertIsNotNone(row)
            self.assertEqual(int(row.fallback_used), 1)
        finally:
            db.close()

    def test_admin_disable_nn_endpoint(self):
        train = self.client.post("/admin/meta-controller/train/fake", headers=self._auth())
        self.assertEqual(train.status_code, 200)
        version = int(train.json()["model_version"])

        promote = self.client.post("/admin/meta-controller/model/promote", json={"model_version": version}, headers=self._auth())
        self.assertEqual(promote.status_code, 200)

        disable = self.client.post("/admin/meta-controller/enable", json={"enabled": False}, headers=self._auth())
        self.assertEqual(disable.status_code, 200)

        status = self.client.get("/admin/meta-controller/status", headers=self._auth())
        self.assertEqual(status.status_code, 200)
        self.assertFalse(bool(status.json().get("enabled")))


if __name__ == "__main__":
    unittest.main()
