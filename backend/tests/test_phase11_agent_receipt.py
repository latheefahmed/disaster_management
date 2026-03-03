import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.allocation import Allocation
from app.models.district import District
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.models.state import State
from app.services.agent_engine import decide_recommendation, run_agent_engine
from app.services.allocation_service import confirm_allocation_receipt
from app.services.signal_service import generate_signals


class Phase11AgentReceiptTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.Session()

        self.db.add_all([
            State(state_code="10", state_name="State 10", latitude=12.9, longitude=77.6),
            State(state_code="20", state_name="State 20", latitude=13.1, longitude=80.2),
        ])
        self.db.add_all([
            District(district_code="1001", district_name="D-1001", state_code="10", demand_mode="baseline_plus_human"),
            District(district_code="2001", district_name="D-2001", state_code="20", demand_mode="baseline_plus_human"),
        ])

        completed_runs = [
            SolverRun(mode="live", status="completed"),
            SolverRun(mode="live", status="completed"),
            SolverRun(mode="live", status="completed"),
        ]
        self.db.add_all(completed_runs)
        self.db.commit()

        self.run_ids = [int(r.id) for r in completed_runs]

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_receipt_confirmation_sets_flags(self):
        alloc = Allocation(
            solver_run_id=self.run_ids[-1],
            request_id=0,
            resource_id="R10",
            district_code="1001",
            state_code="10",
            origin_state="20",
            origin_state_code="20",
            origin_district_code=None,
            time=1,
            allocated_quantity=12.0,
            implied_delay_hours=4.0,
            receipt_confirmed=False,
            receipt_time=None,
            is_unmet=False,
            claimed_quantity=0.0,
            consumed_quantity=0.0,
            returned_quantity=0.0,
            status="allocated",
        )
        self.db.add(alloc)
        self.db.commit()

        out = confirm_allocation_receipt(self.db, allocation_id=int(alloc.id), district_code="1001")
        self.assertTrue(bool(out.receipt_confirmed))
        self.assertIsNotNone(out.receipt_time)

    def test_signal_generation_for_chronic_delay_and_unmet(self):
        for run_id in self.run_ids:
            self.db.add(Allocation(
                solver_run_id=run_id,
                request_id=0,
                resource_id="water",
                district_code="1001",
                state_code="10",
                origin_state="10",
                origin_state_code="10",
                time=1,
                allocated_quantity=8.0,
                implied_delay_hours=1.0,
                receipt_confirmed=False,
                receipt_time=None,
                is_unmet=True,
                claimed_quantity=0.0,
                consumed_quantity=0.0,
                returned_quantity=0.0,
                status="unmet",
            ))

        old_a = Allocation(
            solver_run_id=self.run_ids[-1],
            request_id=0,
            resource_id="R10",
            district_code="1001",
            state_code="10",
            origin_state="20",
            origin_state_code="20",
            time=1,
            allocated_quantity=5.0,
            implied_delay_hours=1.0,
            receipt_confirmed=False,
            receipt_time=None,
            is_unmet=False,
            claimed_quantity=0.0,
            consumed_quantity=0.0,
            returned_quantity=0.0,
            status="allocated",
            created_at=datetime.utcnow() - timedelta(hours=10),
        )
        old_b = Allocation(
            solver_run_id=self.run_ids[-2],
            request_id=0,
            resource_id="R10",
            district_code="1001",
            state_code="10",
            origin_state="20",
            origin_state_code="20",
            time=1,
            allocated_quantity=6.0,
            implied_delay_hours=1.0,
            receipt_confirmed=False,
            receipt_time=None,
            is_unmet=False,
            claimed_quantity=0.0,
            consumed_quantity=0.0,
            returned_quantity=0.0,
            status="allocated",
            created_at=datetime.utcnow() - timedelta(hours=9),
        )
        self.db.add_all([old_a, old_b])

        self.db.add_all([
            ResourceRequest(district_code="1001", state_code="10", resource_id="water", time=1, quantity=2.0, source="human", status="pending"),
            ResourceRequest(district_code="1001", state_code="10", resource_id="food", time=1, quantity=2.0, source="human", status="pending"),
            ResourceRequest(district_code="1001", state_code="10", resource_id="R10", time=1, quantity=2.0, source="human", status="pending"),
        ])
        self.db.commit()

        signals = generate_signals(self.db)
        signal_types = {str(s.get("signal_type")) for s in signals}
        self.assertIn("chronic_unmet", signal_types)
        self.assertIn("chronic_delay", signal_types)
        self.assertIn("repeated_override", signal_types)

    def test_agent_engine_creates_findings_and_recommendations(self):
        for run_id in self.run_ids:
            self.db.add(Allocation(
                solver_run_id=run_id,
                request_id=0,
                resource_id="water",
                district_code="1001",
                state_code="10",
                origin_state="10",
                origin_state_code="10",
                time=1,
                allocated_quantity=5.0,
                implied_delay_hours=0.0,
                receipt_confirmed=False,
                receipt_time=None,
                is_unmet=True,
                claimed_quantity=0.0,
                consumed_quantity=0.0,
                returned_quantity=0.0,
                status="unmet",
            ))
        self.db.commit()

        with patch("app.services.agent_engine.ENABLE_AGENT_ENGINE", True):
            result = run_agent_engine(self.db, trigger="solver_run", context={"solver_run_id": self.run_ids[-1]})

        self.assertTrue(result["enabled"])
        self.assertGreaterEqual(int(result["findings_created"]), 1)
        self.assertGreaterEqual(int(result["recommendations_created"]), 1)

    def test_approving_recommendation_executes_governed_action(self):
        for run_id in self.run_ids:
            self.db.add(Allocation(
                solver_run_id=run_id,
                request_id=0,
                resource_id="water",
                district_code="1001",
                state_code="10",
                origin_state="10",
                origin_state_code="10",
                time=1,
                allocated_quantity=5.0,
                implied_delay_hours=0.0,
                receipt_confirmed=False,
                receipt_time=None,
                is_unmet=True,
                claimed_quantity=0.0,
                consumed_quantity=0.0,
                returned_quantity=0.0,
                status="unmet",
            ))
        self.db.commit()

        with patch("app.services.agent_engine.ENABLE_AGENT_ENGINE", True):
            run_agent_engine(self.db, trigger="unmet_ingest", context={"solver_run_id": self.run_ids[-1]})

        from app.models.agent_recommendation import AgentRecommendation

        rec = self.db.query(AgentRecommendation).filter(AgentRecommendation.status == "pending").first()
        self.assertIsNotNone(rec)

        actor = {"username": "admin_user", "role": "admin", "state_code": "10", "district_code": None}
        out = decide_recommendation(self.db, recommendation_id=int(rec.id), decision="approved", actor=actor)
        self.assertEqual(str(out.status), "approved")


if __name__ == "__main__":
    unittest.main()
