import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.allocation import Allocation
from app.models.claim import Claim
from app.models.district import District
from app.models.solver_run import SolverRun
from app.models.state import State
from app.services.action_service import create_claim, create_consumption, create_return
from app.engine_bridge.ingest import ingest_solver_results


class EscalationLifecycleRuleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.Session()

        self.db.add_all([
            State(state_code="33", state_name="State 33", latitude=12.9, longitude=77.6),
            State(state_code="44", state_name="State 44", latitude=13.1, longitude=80.2),
            District(district_code="603", district_name="District 603", state_code="33", demand_mode="baseline_plus_human"),
        ])
        self.db.commit()

        run = SolverRun(mode="live", status="completed")
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        self.run_id = int(run.id)

        self.db.add_all([
            Allocation(
                solver_run_id=self.run_id,
                request_id=0,
                supply_level="district",
                allocation_source_scope="district",
                allocation_source_code="603",
                resource_id="R5",
                district_code="603",
                state_code="33",
                origin_state="33",
                origin_state_code="33",
                time=0,
                allocated_quantity=20.0,
                is_unmet=False,
                status="allocated",
            ),
            Allocation(
                solver_run_id=self.run_id,
                request_id=0,
                supply_level="state",
                allocation_source_scope="neighbor_state",
                allocation_source_code="44",
                resource_id="R8",
                district_code="603",
                state_code="33",
                origin_state="44",
                origin_state_code="44",
                time=0,
                allocated_quantity=1.0,
                is_unmet=False,
                status="allocated",
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_consumable_can_consume_but_cannot_return(self):
        create_claim(self.db, district_code="603", resource_id="R5", time=0, quantity=10, claimed_by="tester")
        create_consumption(self.db, district_code="603", resource_id="R5", time=0, quantity=5)

        with self.assertRaises(ValueError):
            create_return(self.db, district_code="603", resource_id="R5", state_code="33", time=0, quantity=1, reason="invalid")

    def test_non_consumable_can_return_but_cannot_consume(self):
        create_claim(self.db, district_code="603", resource_id="R8", time=0, quantity=1, claimed_by="tester")

        with self.assertRaises(ValueError):
            create_consumption(self.db, district_code="603", resource_id="R8", time=0, quantity=1)

        returned, _ = create_return(self.db, district_code="603", resource_id="R8", state_code="33", time=0, quantity=1, reason="valid")
        self.assertIsNotNone(returned.id)

    def test_ingest_populates_allocation_source_fields(self):
        run = SolverRun(mode="scenario", status="completed")
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

        with patch("app.engine_bridge.ingest.parse_allocations", return_value=[
            {
                "supply_level": "district",
                "resource_id": "R5",
                "district_code": "603",
                "state_code": "33",
                "time": 0,
                "allocated_quantity": 3.0,
            },
            {
                "supply_level": "state",
                "resource_id": "R8",
                "district_code": "603",
                "state_code": "44",
                "time": 0,
                "allocated_quantity": 1.0,
            },
            {
                "supply_level": "national",
                "resource_id": "R41",
                "district_code": "603",
                "state_code": "33",
                "time": 0,
                "allocated_quantity": 1.0,
            },
        ]), patch("app.engine_bridge.ingest.parse_unmet", return_value=[]), patch("app.engine_bridge.ingest.parse_inventory_snapshots", return_value=[]), patch("app.engine_bridge.ingest.parse_shipment_plan", return_value=[]):
            ingest_solver_results(self.db, solver_run_id=int(run.id))

        rows = self.db.query(Allocation).filter(Allocation.solver_run_id == int(run.id), Allocation.is_unmet == False).all()
        by_resource = {str(r.resource_id): r for r in rows}

        self.assertEqual(str(by_resource["R5"].allocation_source_scope), "district")
        self.assertEqual(str(by_resource["R5"].allocation_source_code), "603")

        self.assertEqual(str(by_resource["R8"].allocation_source_scope), "neighbor_state")
        self.assertEqual(str(by_resource["R8"].allocation_source_code), "44")

        self.assertEqual(str(by_resource["R41"].allocation_source_scope), "national")
        self.assertEqual(str(by_resource["R41"].allocation_source_code), "NATIONAL")


if __name__ == "__main__":
    unittest.main()
