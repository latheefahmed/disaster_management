import math
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import get_db
from app.engine_bridge.solver_lock import solver_execution_lock
from app.main import app
from app.models.allocation import Allocation
from app.models.demand_learning_event import DemandLearningEvent
from app.models.demand_weight_model import DemandWeightModel
from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.request import ResourceRequest
from app.models.resource import Resource
from app.models.solver_run import SolverRun
from app.models.state import State
from app.models.user import User
from app.services import demand_learning_service as dls
from app.services.request_service import merge_baseline_and_human, get_district_requests_view
from app.services.scenario_runner import _assemble_final_demand
from app.utils.hashing import hash_password


class Phase6HardeningTests(unittest.TestCase):
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
                DemandLearningEvent,
                DemandWeightModel,
                FinalDemand,
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
            ])
            db.add_all([
                District(district_code="101", district_name="District 101", state_code="10", demand_mode="baseline_plus_human"),
            ])
            db.add_all([
                Resource(resource_id="1", canonical_name="water", resource_name="Water", ethical_priority=1.0),
                Resource(resource_id="2", canonical_name="food", resource_name="Food", ethical_priority=2.0),
            ])
            db.add(
                User(
                    username="district_user",
                    password_hash=hash_password("pw"),
                    role="district",
                    state_code="10",
                    district_code="101",
                )
            )
            db.commit()
        finally:
            db.close()

    def _login_district_token(self) -> str:
        res = self.client.post("/auth/login", json={"username": "district_user", "password": "pw"})
        self.assertEqual(res.status_code, 200)
        return res.json()["access_token"]

    def _seed_run(self, db, mode: str = "live", status: str = "completed") -> SolverRun:
        run = SolverRun(mode=mode, status=status)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def _insert_learning_events(self, db, count: int, resource_id: str = "1", baseline: float = 10.0, human: float = 10.0, unmet: float = 2.0):
        rows = []
        for i in range(count):
            final_demand = baseline + human
            allocated = max(0.0, final_demand - unmet)
            rows.append(
                DemandLearningEvent(
                    solver_run_id=1,
                    district_code="101",
                    resource_id=resource_id,
                    time=(i % 3),
                    baseline_demand=baseline,
                    human_demand=human,
                    final_demand=final_demand,
                    allocated=allocated,
                    unmet=unmet,
                    priority=1.0,
                    urgency=1.0,
                )
            )
        db.add_all(rows)
        db.commit()

    # Category A
    def test_A1_learning_disabled_matches_phase5b_merge(self):
        db = self.Session()
        try:
            baseline = pd.DataFrame([
                {"district_code": "101", "resource_id": "1", "time": 1, "demand": 10.0}
            ])
            human = pd.DataFrame([
                {"district_code": "101", "resource_id": "1", "time": 1, "demand": 3.0}
            ])
            with patch.object(dls, "ENABLE_DEMAND_LEARNING", False):
                final_df = _assemble_final_demand(db, baseline, human)
            self.assertEqual(float(final_df.iloc[0]["demand"]), 13.0)
        finally:
            db.close()

    def test_A2_learning_disabled_is_deterministic(self):
        db = self.Session()
        try:
            baseline = pd.DataFrame([
                {"district_code": "101", "resource_id": "1", "time": 1, "demand": 11.0},
                {"district_code": "101", "resource_id": "2", "time": 2, "demand": 7.0},
            ])
            human = pd.DataFrame([
                {"district_code": "101", "resource_id": "1", "time": 1, "demand": 4.0},
                {"district_code": "101", "resource_id": "2", "time": 2, "demand": 6.0},
            ])
            with patch.object(dls, "ENABLE_DEMAND_LEARNING", False):
                run1 = _assemble_final_demand(db, baseline, human).sort_values(["resource_id", "time"]).reset_index(drop=True)
                run2 = _assemble_final_demand(db, baseline, human).sort_values(["resource_id", "time"]).reset_index(drop=True)
            pd.testing.assert_frame_equal(run1, run2)
        finally:
            db.close()

    # Category B
    def test_B1_learning_events_capture_integrity(self):
        db = self.Session()
        try:
            run = self._seed_run(db)
            db.add_all([
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    resource_id="1",
                    district_code="101",
                    state_code="10",
                    time=1,
                    allocated_quantity=12.0,
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
            db.add(
                ResourceRequest(
                    district_code="101",
                    state_code="10",
                    resource_id="1",
                    time=1,
                    quantity=15.0,
                    priority=2,
                    urgency=3,
                    confidence=1.0,
                    source="human",
                    status="pending",
                    included_in_run=1,
                    queued=0,
                )
            )
            db.commit()

            baseline = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "baseline_demand": 5.0}])
            human = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "human_demand": 10.0}])
            final_df = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand": 15.0}])

            with patch.object(dls, "ENABLE_DEMAND_LEARNING", True):
                rows = dls.capture_demand_learning_events(
                    db,
                    solver_run_id=run.id,
                    baseline_df=baseline,
                    human_df=human,
                    final_df=final_df,
                )
                db.commit()

            self.assertGreater(rows, 0)
            event = db.query(DemandLearningEvent).first()
            self.assertIsNotNone(event)
            self.assertIsNotNone(event.solver_run_id)
            self.assertIsNotNone(event.baseline_demand)
            self.assertIsNotNone(event.human_demand)
        finally:
            db.close()

    def test_B2_conservation_final_equals_allocated_plus_unmet(self):
        db = self.Session()
        try:
            run = self._seed_run(db)
            db.add_all([
                FinalDemand(
                    solver_run_id=run.id,
                    district_code="101",
                    state_code="10",
                    resource_id="1",
                    time=1,
                    demand_quantity=15.0,
                    demand_mode="baseline_plus_human",
                    source_mix="merged",
                ),
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    resource_id="1",
                    district_code="101",
                    state_code="10",
                    time=1,
                    allocated_quantity=12.0,
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
            db.commit()

            final_total = float(np.sum([r.demand_quantity for r in db.query(FinalDemand).filter(FinalDemand.solver_run_id == run.id).all()]))
            alloc_total = float(np.sum([r.allocated_quantity for r in db.query(Allocation).filter(Allocation.solver_run_id == run.id, Allocation.is_unmet == False).all()]))
            unmet_total = float(np.sum([r.allocated_quantity for r in db.query(Allocation).filter(Allocation.solver_run_id == run.id, Allocation.is_unmet == True).all()]))

            self.assertAlmostEqual(final_total, alloc_total + unmet_total, places=6)
        finally:
            db.close()

    # Category C
    def test_C1_trained_weights_respect_constraints(self):
        db = self.Session()
        try:
            self._insert_learning_events(db, count=60, resource_id="1", baseline=10.0, human=8.0, unmet=4.0)
            out = dls.train_demand_weight_models(db)
            db.commit()
            self.assertGreaterEqual(out["trained_models"], 1)

            model = db.query(DemandWeightModel).order_by(DemandWeightModel.id.desc()).first()
            self.assertTrue(0.0 <= float(model.w_baseline) <= 2.0)
            self.assertTrue(0.0 <= float(model.w_human) <= 2.0)
            self.assertGreaterEqual(float(model.w_baseline) + float(model.w_human), 0.5)
        finally:
            db.close()

    def test_C2_insufficient_samples_no_model_created(self):
        db = self.Session()
        try:
            self._insert_learning_events(db, count=5, resource_id="1", baseline=10.0, human=5.0, unmet=1.0)
            with patch.object(dls, "DEMAND_LEARNING_MIN_SAMPLES", 20):
                out = dls.train_demand_weight_models(db)
                db.commit()
            self.assertEqual(out["trained_models"], 0)
            self.assertEqual(db.query(DemandWeightModel).count(), 0)
        finally:
            db.close()

    def test_C3_repeated_training_has_low_drift(self):
        db = self.Session()
        try:
            self._insert_learning_events(db, count=80, resource_id="1", baseline=9.0, human=11.0, unmet=3.0)
            first = dls.train_demand_weight_models(db)
            db.commit()
            second = dls.train_demand_weight_models(db)
            db.commit()
            self.assertGreaterEqual(first["trained_models"], 1)
            self.assertGreaterEqual(second["trained_models"], 1)

            models = db.query(DemandWeightModel).filter(DemandWeightModel.resource_id == "1").order_by(DemandWeightModel.id.desc()).limit(2).all()
            self.assertEqual(len(models), 2)
            drift = abs(float(models[0].w_baseline) - float(models[1].w_baseline)) + abs(float(models[0].w_human) - float(models[1].w_human))
            self.assertLess(drift, 0.2)
        finally:
            db.close()

    # Category D
    def test_D1_inference_changes_demand_when_enabled_and_model_exists(self):
        db = self.Session()
        try:
            db.add(
                DemandWeightModel(
                    district_code=None,
                    resource_id="1",
                    time_slot=None,
                    w_baseline=0.3,
                    w_human=1.4,
                    confidence=0.8,
                    trained_on_start=datetime.utcnow() - timedelta(days=2),
                    trained_on_end=datetime.utcnow() - timedelta(days=1),
                )
            )
            db.commit()

            merged = pd.DataFrame([
                {
                    "district_code": "101",
                    "resource_id": "1",
                    "time": 1,
                    "demand_baseline": 10.0,
                    "demand_human": 5.0,
                    "demand_mode": "baseline_plus_human",
                    "source_mix": "merged",
                }
            ])

            with patch.object(dls, "ENABLE_DEMAND_LEARNING", True):
                weighted, model_ids = dls.apply_weight_models_to_merged_demand(db, merged)

            self.assertTrue(model_ids)
            self.assertNotEqual(float(weighted.iloc[0]["demand"]), 15.0)
        finally:
            db.close()

    def test_D2_inference_disabled_falls_back_to_sum(self):
        db = self.Session()
        try:
            merged = pd.DataFrame([
                {
                    "district_code": "101",
                    "resource_id": "1",
                    "time": 1,
                    "demand_baseline": 10.0,
                    "demand_human": 5.0,
                    "demand_mode": "baseline_plus_human",
                    "source_mix": "merged",
                }
            ])
            with patch.object(dls, "ENABLE_DEMAND_LEARNING", False):
                weighted, model_ids = dls.apply_weight_models_to_merged_demand(db, merged)
            self.assertEqual(model_ids, [])
            self.assertEqual(float(weighted.iloc[0]["demand"]), 15.0)
        finally:
            db.close()

    def test_D3_no_model_falls_back_even_when_enabled(self):
        db = self.Session()
        try:
            db.query(DemandWeightModel).delete()
            db.commit()
            merged = pd.DataFrame([
                {
                    "district_code": "101",
                    "resource_id": "1",
                    "time": 1,
                    "demand_baseline": 8.0,
                    "demand_human": 2.0,
                    "demand_mode": "baseline_plus_human",
                    "source_mix": "merged",
                }
            ])
            with patch.object(dls, "ENABLE_DEMAND_LEARNING", True):
                weighted, model_ids = dls.apply_weight_models_to_merged_demand(db, merged)
            self.assertFalse(model_ids)
            self.assertEqual(float(weighted.iloc[0]["demand"]), 10.0)
        finally:
            db.close()

    # Category E
    def test_E1_malformed_bearer_token_rejected(self):
        res = self.client.get("/district/me", headers={"Authorization": "Bearer not-hex-token"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid token format.", res.text)

    def test_E2_unknown_resource_rejected(self):
        token = self._login_district_token()
        headers = {"Authorization": f"Bearer {token}"}
        with patch("app.services.request_service._start_live_solver_run", return_value=1):
            res = self.client.post(
                "/district/request",
                headers=headers,
                json={
                    "resource_id": "unknown_resource_xyz",
                    "time": 1,
                    "quantity": 5,
                    "priority": 1,
                    "urgency": 1,
                    "confidence": 1.0,
                    "source": "human",
                },
            )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unknown resource.", res.text)

    def test_E3_free_text_alias_rejected(self):
        token = self._login_district_token()
        headers = {"Authorization": f"Bearer {token}"}
        with patch("app.services.request_service._start_live_solver_run", return_value=1):
            res = self.client.post(
                "/district/request",
                headers=headers,
                json={
                    "resource_id": "water_tanker_alias",
                    "time": 1,
                    "quantity": 5,
                    "priority": 1,
                    "urgency": 1,
                    "confidence": 1.0,
                    "source": "human",
                },
            )
        self.assertEqual(res.status_code, 400)

    # Category F
    def test_F1_metadata_resources_exposes_canonical_name(self):
        res = self.client.get("/metadata/resources")
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload)
        self.assertIn("resource_id", payload[0])
        self.assertIn("canonical_name", payload[0])

    def test_F2_request_contract_requires_resource_id(self):
        token = self._login_district_token()
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.post(
            "/district/request",
            headers=headers,
            json={
                "resource_name": "water",
                "time": 1,
                "quantity": 5,
                "priority": 1,
                "urgency": 1,
                "confidence": 1.0,
                "source": "human",
            },
        )
        self.assertEqual(res.status_code, 422)

    def test_F3_coverage_uses_final_demand(self):
        db = self.Session()
        try:
            run = self._seed_run(db)
            db.add(
                ResourceRequest(
                    district_code="101",
                    state_code="10",
                    resource_id="1",
                    time=1,
                    quantity=15.0,
                    priority=1,
                    urgency=1,
                    confidence=1.0,
                    source="human",
                    status="pending",
                    included_in_run=1,
                    queued=0,
                )
            )
            db.add_all([
                FinalDemand(
                    solver_run_id=run.id,
                    district_code="101",
                    state_code="10",
                    resource_id="1",
                    time=1,
                    demand_quantity=15.0,
                    demand_mode="baseline_plus_human",
                    source_mix="merged",
                ),
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    resource_id="1",
                    district_code="101",
                    state_code="10",
                    time=1,
                    allocated_quantity=12.0,
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
            db.commit()

            rows = get_district_requests_view(db, district_code="101")
            self.assertTrue(rows)
            first = rows[0]
            self.assertAlmostEqual(float(first["final_demand_quantity"]), 15.0, places=6)
            self.assertTrue(first["lineage_consistent"])
        finally:
            db.close()

    # Category G
    def test_G1_zero_baseline_nonzero_human_no_nan(self):
        db = self.Session()
        try:
            db.add(DemandWeightModel(resource_id="1", district_code=None, time_slot=None, w_baseline=0.2, w_human=1.2, confidence=0.7))
            db.commit()
            merged = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand_baseline": 0.0, "demand_human": 10.0, "demand_mode": "baseline_plus_human", "source_mix": "merged"}])
            with patch.object(dls, "ENABLE_DEMAND_LEARNING", True):
                out, _ = dls.apply_weight_models_to_merged_demand(db, merged)
            self.assertTrue(np.isfinite(out["demand"].to_numpy(dtype=float)).all())
        finally:
            db.close()

    def test_G2_zero_human_nonzero_baseline_no_nan(self):
        db = self.Session()
        try:
            db.add(DemandWeightModel(resource_id="1", district_code=None, time_slot=None, w_baseline=1.1, w_human=0.1, confidence=0.7))
            db.commit()
            merged = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand_baseline": 10.0, "demand_human": 0.0, "demand_mode": "baseline_plus_human", "source_mix": "merged"}])
            with patch.object(dls, "ENABLE_DEMAND_LEARNING", True):
                out, _ = dls.apply_weight_models_to_merged_demand(db, merged)
            self.assertTrue(np.isfinite(out["demand"].to_numpy(dtype=float)).all())
        finally:
            db.close()

    def test_G3_zero_zero_stable_training(self):
        db = self.Session()
        try:
            self._insert_learning_events(db, count=40, resource_id="1", baseline=0.0, human=0.0, unmet=0.0)
            out = dls.train_demand_weight_models(db)
            db.commit()
            self.assertGreaterEqual(out["trained_models"], 1)
            model = db.query(DemandWeightModel).order_by(DemandWeightModel.id.desc()).first()
            self.assertTrue(math.isfinite(float(model.w_baseline)))
            self.assertTrue(math.isfinite(float(model.w_human)))
        finally:
            db.close()

    # Category H
    def test_H_drift_control_human_weight_increases_gradually(self):
        db = self.Session()
        try:
            evolution = []
            for i in range(10):
                self._insert_learning_events(
                    db,
                    count=25,
                    resource_id="1",
                    baseline=5.0,
                    human=10.0 + i,
                    unmet=6.0 + (2.0 * i),
                )
                out = dls.train_demand_weight_models(db)
                db.commit()
                self.assertGreaterEqual(out["trained_models"], 1)
                latest = db.query(DemandWeightModel).filter(DemandWeightModel.resource_id == "1").order_by(DemandWeightModel.id.desc()).first()
                evolution.append(float(latest.w_human))

            self.assertGreater(evolution[-1], evolution[0])
            deltas = [abs(evolution[i] - evolution[i - 1]) for i in range(1, len(evolution))]
            self.assertLess(max(deltas), 1.0)
            self.assertLess(max(evolution[:3]), 2.0)
        finally:
            db.close()

    # Category I
    def test_I_solver_lock_serializes_parallel_sections_and_model_id_consistent(self):
        db = self.Session()
        try:
            model = DemandWeightModel(resource_id="1", district_code=None, time_slot=None, w_baseline=1.0, w_human=1.0, confidence=0.8)
            db.add(model)
            run1 = SolverRun(mode="live", status="running")
            run2 = SolverRun(mode="live", status="running")
            db.add_all([run1, run2])
            db.commit()
            db.refresh(run1)
            db.refresh(run2)
            run_ids = [run1.id, run2.id]
            model_id = int(model.id)
        finally:
            db.close()

        active = {"count": 0, "max": 0}
        counter_lock = threading.Lock()

        def worker(run_id: int):
            local_db = self.Session()
            try:
                with solver_execution_lock:
                    with counter_lock:
                        active["count"] += 1
                        active["max"] = max(active["max"], active["count"])
                    time.sleep(0.05)
                    latest_model = local_db.query(DemandWeightModel).order_by(DemandWeightModel.created_at.desc(), DemandWeightModel.id.desc()).first()
                    run = local_db.query(SolverRun).filter(SolverRun.id == run_id).first()
                    run.weight_model_id = int(latest_model.id)
                    local_db.commit()
                    with counter_lock:
                        active["count"] -= 1
            finally:
                local_db.close()

        threads = [threading.Thread(target=worker, args=(rid,)) for rid in run_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        verify_db = self.Session()
        try:
            runs = verify_db.query(SolverRun).filter(SolverRun.id.in_(run_ids)).all()
            self.assertEqual(active["max"], 1)
            self.assertTrue(all(r.weight_model_id == model_id for r in runs))
        finally:
            verify_db.close()

    # Category J
    def test_J_model_versioning_attaches_and_preserves_history(self):
        db = self.Session()
        try:
            model1 = DemandWeightModel(
                resource_id="1",
                district_code=None,
                time_slot=None,
                w_baseline=1.0,
                w_human=1.0,
                confidence=0.7,
                created_at=datetime.utcnow() - timedelta(days=1),
            )
            db.add(model1)
            db.commit()
            db.refresh(model1)

            run1 = SolverRun(mode="live", status="completed")
            db.add(run1)
            db.commit()
            db.refresh(run1)

            base = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand": 10.0}])
            human = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand": 5.0}])

            with patch.object(dls, "ENABLE_DEMAND_LEARNING", True):
                _, ids1 = merge_baseline_and_human(db, base, human)
            run1.weight_model_id = max(ids1) if ids1 else None
            db.commit()

            model2 = DemandWeightModel(
                resource_id="1",
                district_code=None,
                time_slot=None,
                w_baseline=0.8,
                w_human=1.2,
                confidence=0.8,
                created_at=datetime.utcnow(),
            )
            db.add(model2)
            db.commit()
            db.refresh(model2)

            run2 = SolverRun(mode="live", status="completed")
            db.add(run2)
            db.commit()
            db.refresh(run2)

            with patch.object(dls, "ENABLE_DEMAND_LEARNING", True):
                _, ids2 = merge_baseline_and_human(db, base, human)
            run2.weight_model_id = max(ids2) if ids2 else None
            db.commit()

            self.assertEqual(int(run1.weight_model_id), int(model1.id))
            self.assertEqual(int(run2.weight_model_id), int(model2.id))
        finally:
            db.close()

    # Category K
    def test_K_feature_flag_rollback_restores_phase5b_behavior(self):
        db = self.Session()
        try:
            db.add(DemandWeightModel(resource_id="1", district_code=None, time_slot=None, w_baseline=0.1, w_human=1.8, confidence=0.9))
            db.commit()

            baseline = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand": 10.0}])
            human = pd.DataFrame([{"district_code": "101", "resource_id": "1", "time": 1, "demand": 10.0}])

            with patch.object(dls, "ENABLE_DEMAND_LEARNING", False):
                final_df = _assemble_final_demand(db, baseline, human)

            self.assertEqual(float(final_df.iloc[0]["demand"]), 20.0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
