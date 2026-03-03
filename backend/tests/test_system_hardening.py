import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.district import District
from app.models.solver_run import SolverRun
from app.models.allocation import Allocation
from app.models.claim import Claim
from app.models.return_ import Return
from app.models.consumption import Consumption
from app.models.pool_transaction import PoolTransaction
from app.models.audit_log import AuditLog
from app.services.action_service import create_claim, create_return
from app.engine_bridge.ingest import ingest_solver_results
from app.services.scenario_runner import _assemble_final_demand


class SystemHardeningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed_live_run(self):
        run = SolverRun(mode='live', status='completed')
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def test_claim_reduces_available_allocation_snapshot(self):
        run = self._seed_live_run()
        self.db.add(District(district_code='101', district_name='D1', state_code='10', demand_mode='baseline_plus_human'))
        self.db.add(
            Allocation(
                solver_run_id=run.id,
                request_id=0,
                resource_id='water',
                district_code='101',
                state_code='10',
                time=1,
                allocated_quantity=100.0,
                is_unmet=False,
            )
        )
        self.db.commit()

        _, snapshot = create_claim(
            self.db,
            district_code='101',
            resource_id='water',
            time=1,
            quantity=40,
            claimed_by='tester',
        )

        self.assertEqual(snapshot['claimed_quantity'], 40.0)
        self.assertEqual(snapshot['remaining_quantity'], 40.0)

        alloc = self.db.query(Allocation).filter(Allocation.solver_run_id == run.id).first()
        self.assertEqual(float(alloc.claimed_quantity), 40.0)
        self.assertEqual(str(alloc.status), 'claimed')

    def test_return_increases_pool_and_updates_snapshot(self):
        run = self._seed_live_run()
        self.db.add(District(district_code='102', district_name='D2', state_code='10', demand_mode='baseline_plus_human'))
        self.db.add(
            Allocation(
                solver_run_id=run.id,
                request_id=0,
                resource_id='medicine',
                district_code='102',
                state_code='10',
                time=1,
                allocated_quantity=50.0,
                is_unmet=False,
            )
        )
        self.db.commit()

        create_claim(self.db, '102', 'medicine', 1, 30, 'tester')
        _, snapshot = create_return(
            self.db,
            district_code='102',
            resource_id='medicine',
            state_code='10',
            time=1,
            quantity=10,
            reason='manual',
        )

        self.assertEqual(snapshot['returned_quantity'], 10.0)
        self.assertEqual(snapshot['remaining_quantity'], 20.0)

        pool_sum = self.db.query(PoolTransaction).filter(PoolTransaction.resource_id == 'medicine').all()
        self.assertEqual(sum(float(r.quantity_delta) for r in pool_sum), 10.0)

    def test_ingest_creates_allocations_and_unmet_rows(self):
        self.db.add(District(district_code='201', district_name='D3', state_code='20', demand_mode='baseline_plus_human'))
        self.db.commit()

        with patch('app.engine_bridge.ingest.parse_allocations', return_value=[
            {
                'supply_level': 'state',
                'resource_id': 'water',
                'district_code': '201',
                'state_code': '20',
                'time': 1,
                'allocated_quantity': 70.0,
            }
        ]), patch('app.engine_bridge.ingest.parse_unmet', return_value=[
            {
                'resource_id': 'water',
                'district_code': '201',
                'time': 1,
                'unmet_quantity': 5.0,
            }
        ]):
            ingest_solver_results(self.db, solver_run_id=999)

        rows = self.db.query(Allocation).filter(Allocation.solver_run_id == 999).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(1 for r in rows if r.is_unmet), 1)
        self.assertEqual(sum(1 for r in rows if not r.is_unmet), 1)

    def test_demand_mode_human_only_excludes_baseline(self):
        import pandas as pd

        self.db.add(District(district_code='301', district_name='D4', state_code='30', demand_mode='human_only'))
        self.db.commit()

        baseline = pd.DataFrame([
            {'district_code': '301', 'resource_id': 'food', 'time': 1, 'demand': 100.0}
        ])
        human = pd.DataFrame([
            {'district_code': '301', 'resource_id': 'food', 'time': 1, 'demand': 25.0}
        ])

        final_df = _assemble_final_demand(self.db, baseline, human)
        self.assertEqual(len(final_df.index), 1)
        self.assertEqual(float(final_df.iloc[0]['demand']), 25.0)


if __name__ == '__main__':
    unittest.main()
