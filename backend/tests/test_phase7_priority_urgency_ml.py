import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.allocation import Allocation
from app.models.priority_urgency_event import PriorityUrgencyEvent
from app.models.priority_urgency_model import PriorityUrgencyModel
from app.models.request import ResourceRequest
from app.models.request_prediction import RequestPrediction
from app.models.resource import Resource
from app.models.solver_run import SolverRun
from app.models.state import State
from app.models.district import District
from app.services.request_service import create_request
from app.services.priority_urgency_ml_service import (
    capture_priority_urgency_events,
    train_priority_urgency_models,
)
from app.services import priority_urgency_ml_service as pu_service


class Phase7PriorityUrgencyMLTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.Session()

        self.db.add(State(state_code="10", state_name="State 10"))
        self.db.add(District(district_code="101", district_name="District 101", state_code="10", demand_mode="baseline_plus_human"))
        self.db.add(Resource(resource_id="1", canonical_name="water", resource_name="Water", ethical_priority=1.0))
        self.db.commit()

        self.user = {"district_code": "101", "state_code": "10"}

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _make_model_payload(self, feature_count: int):
        return {
            "model": {
                "weights": [0.1] * feature_count,
                "bias": 0.2,
                "mean": [0.0] * feature_count,
                "std": [1.0] * feature_count,
            },
            "evaluation": {
                "mae": 0.1,
                "rmse": 0.2,
                "samples": 100,
            },
        }

    def test_inference_creates_prediction_when_human_values_missing(self):
        feature_count = len(pu_service.FEATURE_COLUMNS)
        self.db.add(PriorityUrgencyModel(model_type="priority", version=1, metrics_json=self._make_model_payload(feature_count)))
        self.db.add(PriorityUrgencyModel(model_type="urgency", version=1, metrics_json=self._make_model_payload(feature_count)))
        self.db.commit()

        data = SimpleNamespace(
            resource_id="1",
            time=1,
            quantity=10.0,
            priority=None,
            urgency=None,
            confidence=1.0,
            source="human",
        )

        with patch("app.services.request_service._start_live_solver_run", return_value=101), patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True):
            out = create_request(self.db, self.user, data)

        pred = self.db.query(RequestPrediction).order_by(RequestPrediction.id.desc()).first()
        self.assertEqual(out["status"], "accepted")
        self.assertIsNotNone(pred)
        self.assertIsNotNone(pred.predicted_priority)
        self.assertIsNotNone(pred.predicted_urgency)

    def test_human_values_remain_authoritative(self):
        feature_count = len(pu_service.FEATURE_COLUMNS)
        self.db.add(PriorityUrgencyModel(model_type="priority", version=1, metrics_json=self._make_model_payload(feature_count)))
        self.db.add(PriorityUrgencyModel(model_type="urgency", version=1, metrics_json=self._make_model_payload(feature_count)))
        self.db.commit()

        data = SimpleNamespace(
            resource_id="1",
            time=1,
            quantity=10.0,
            priority=5,
            urgency=4,
            confidence=1.0,
            source="human",
        )

        with patch("app.services.request_service._start_live_solver_run", return_value=102), patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True):
            out = create_request(self.db, self.user, data)

        req = self.db.query(ResourceRequest).filter(ResourceRequest.id == out["request_id"]).first()
        pred = self.db.query(RequestPrediction).filter(RequestPrediction.request_id == req.id).order_by(RequestPrediction.id.desc()).first()

        self.assertEqual(int(req.priority), 5)
        self.assertEqual(int(req.urgency), 4)
        self.assertIsNone(pred)

    def test_feature_flag_disabled_predictions_not_inferred(self):
        data = SimpleNamespace(
            resource_id="1",
            time=1,
            quantity=10.0,
            priority=None,
            urgency=None,
            confidence=1.0,
            source="human",
        )

        with patch("app.services.request_service._start_live_solver_run", return_value=103), patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", False):
            create_request(self.db, self.user, data)

        pred = self.db.query(RequestPrediction).order_by(RequestPrediction.id.desc()).first()
        self.assertIsNone(pred)

    def test_capture_priority_urgency_events_full_resolution(self):
        run = SolverRun(mode="live", status="completed")
        self.db.add(run)
        self.db.flush()

        req1 = ResourceRequest(
            district_code="101",
            state_code="10",
            resource_id="1",
            time=1,
            quantity=8.0,
            priority=3,
            urgency=2,
            confidence=1.0,
            source="human",
            status="pending",
            included_in_run=1,
            queued=0,
        )
        req2 = ResourceRequest(
            district_code="101",
            state_code="10",
            resource_id="1",
            time=1,
            quantity=4.0,
            priority=None,
            urgency=None,
            confidence=0.8,
            source="human",
            status="pending",
            included_in_run=1,
            queued=0,
        )
        self.db.add_all([req1, req2])
        self.db.flush()

        self.db.add_all([
            Allocation(
                solver_run_id=run.id,
                request_id=0,
                resource_id="1",
                district_code="101",
                state_code="10",
                time=1,
                allocated_quantity=9.0,
                is_unmet=False,
            ),
            Allocation(
                solver_run_id=run.id,
                request_id=0,
                resource_id="1",
                district_code="101",
                state_code="10",
                time=1,
                allocated_quantity=3.0,
                is_unmet=True,
            ),
        ])
        self.db.commit()

        baseline_df = pd.DataFrame([
            {"district_code": "101", "resource_id": "1", "time": 1, "demand": 2.0}
        ])
        final_df = pd.DataFrame([
            {"district_code": "101", "resource_id": "1", "time": 1, "demand": 12.0}
        ])

        with patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True):
            rows = capture_priority_urgency_events(
                self.db,
                solver_run_id=run.id,
                baseline_df=baseline_df,
                final_df=final_df,
                request_ids=[req1.id, req2.id],
            )
            self.db.commit()

        self.assertEqual(rows, 2)
        events = self.db.query(PriorityUrgencyEvent).filter(PriorityUrgencyEvent.solver_run_id == run.id).all()
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e.baseline_demand is not None for e in events))
        self.assertTrue(all(e.final_demand is not None for e in events))

    def test_training_persists_versioned_models(self):
        now = pd.Timestamp.utcnow().to_pydatetime()
        self.db.add_all([
            PriorityUrgencyEvent(
                solver_run_id=1,
                district_code="101",
                resource_id="1",
                time=1,
                baseline_demand=2.0,
                human_quantity=10.0,
                final_demand=12.0,
                allocated=7.0,
                unmet=5.0,
                human_priority=4.0,
                human_urgency=5.0,
                severity_index=0.8,
                infrastructure_damage_index=0.7,
                population_exposed=0.6,
                created_at=now,
            )
            for _ in range(70)
        ])
        self.db.commit()

        with patch.object(pu_service, "ENABLE_PRIORITY_URGENCY_ML", True), patch.object(pu_service, "PRIORITY_URGENCY_MIN_SAMPLES", 50):
            out1 = train_priority_urgency_models(self.db)
            self.db.commit()
            out2 = train_priority_urgency_models(self.db)
            self.db.commit()

        self.assertTrue(out1["priority"]["trained"])
        self.assertTrue(out1["urgency"]["trained"])
        self.assertTrue(out2["priority"]["trained"])

        p_models = self.db.query(PriorityUrgencyModel).filter(PriorityUrgencyModel.model_type == "priority").order_by(PriorityUrgencyModel.version.asc()).all()
        u_models = self.db.query(PriorityUrgencyModel).filter(PriorityUrgencyModel.model_type == "urgency").order_by(PriorityUrgencyModel.version.asc()).all()
        self.assertGreaterEqual(len(p_models), 2)
        self.assertGreaterEqual(len(u_models), 2)
        self.assertLess(p_models[0].version, p_models[-1].version)
        self.assertLess(u_models[0].version, u_models[-1].version)


if __name__ == "__main__":
    unittest.main()
