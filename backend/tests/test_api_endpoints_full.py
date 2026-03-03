import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.deps import get_db
from app.database import Base
from app.utils.hashing import hash_password

from app.models.user import User
from app.models.state import State
from app.models.district import District
from app.models.resource import Resource
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.models.allocation import Allocation
from app.models.scenario import Scenario
from app.models.scenario_request import ScenarioRequest
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.pool_transaction import PoolTransaction
from app.models.stock_refill_transaction import StockRefillTransaction
from app.models.mutual_aid_request import MutualAidRequest
from app.models.claim import Claim
from app.models.consumption import Consumption
from app.models.return_ import Return


class FullApiEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            'sqlite://',
            connect_args={'check_same_thread': False},
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
                Return,
                Consumption,
                Claim,
                MutualAidRequest,
                PoolTransaction,
                StockRefillTransaction,
                ScenarioNationalStock,
                ScenarioStateStock,
                ScenarioRequest,
                Scenario,
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
                State(state_code='10', state_name='State 10', latitude=12.9, longitude=77.6),
                State(state_code='20', state_name='State 20', latitude=13.1, longitude=80.2),
            ])
            db.add_all([
                District(district_code='101', district_name='District 101', state_code='10', demand_mode='baseline_plus_human'),
                District(district_code='102', district_name='District 102', state_code='10', demand_mode='baseline_plus_human'),
                District(district_code='201', district_name='District 201', state_code='20', demand_mode='baseline_plus_human'),
            ])
            db.add_all([
                Resource(resource_id='water', resource_name='Water', ethical_priority=1.0),
                Resource(resource_id='food', resource_name='Food', ethical_priority=2.0),
                Resource(resource_id='R10', resource_name='boats', ethical_priority=3.0),
            ])
            db.add_all([
                User(username='district_user', password_hash=hash_password('pw'), role='district', state_code='10', district_code='101'),
                User(username='state_user', password_hash=hash_password('pw'), role='state', state_code='10', district_code=None),
                User(username='national_user', password_hash=hash_password('pw'), role='national', state_code=None, district_code=None),
                User(username='admin_user', password_hash=hash_password('pw'), role='admin', state_code=None, district_code=None),
            ])

            run = SolverRun(mode='live', status='completed')
            db.add(run)
            db.commit()
            db.refresh(run)

            db.add_all([
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    resource_id='water',
                    district_code='101',
                    state_code='10',
                    time=1,
                    allocated_quantity=100.0,
                    is_unmet=False,
                    claimed_quantity=0.0,
                    consumed_quantity=0.0,
                    returned_quantity=0.0,
                    status='allocated',
                ),
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    resource_id='food',
                    district_code='101',
                    state_code='10',
                    time=1,
                    allocated_quantity=30.0,
                    is_unmet=True,
                    claimed_quantity=0.0,
                    consumed_quantity=0.0,
                    returned_quantity=0.0,
                    status='unmet',
                ),
                Allocation(
                    solver_run_id=run.id,
                    request_id=0,
                    resource_id='R10',
                    district_code='101',
                    state_code='10',
                    time=1,
                    allocated_quantity=20.0,
                    is_unmet=False,
                    claimed_quantity=0.0,
                    consumed_quantity=0.0,
                    returned_quantity=0.0,
                    status='allocated',
                ),
            ])

            db.add_all([
                ResourceRequest(
                    district_code='101',
                    state_code='10',
                    resource_id='water',
                    time=1,
                    quantity=50.0,
                    priority=1,
                    urgency=1,
                    confidence=1.0,
                    source='human',
                    status='pending',
                ),
                ResourceRequest(
                    district_code='102',
                    state_code='10',
                    resource_id='food',
                    time=1,
                    quantity=20.0,
                    priority=1,
                    urgency=1,
                    confidence=1.0,
                    source='human',
                    status='escalated_national',
                ),
            ])

            db.add(PoolTransaction(
                state_code='10',
                district_code='101',
                resource_id='water',
                time=1,
                quantity_delta=40.0,
                reason='seed',
                actor_role='system',
                actor_id='seed',
            ))
            db.add(PoolTransaction(
                state_code='10',
                district_code='101',
                resource_id='R10',
                time=1,
                quantity_delta=25.0,
                reason='seed_returnable',
                actor_role='system',
                actor_id='seed',
            ))

            db.commit()
        finally:
            db.close()

        self.tokens = {
            'district': self._login('district_user', 'pw'),
            'state': self._login('state_user', 'pw'),
            'national': self._login('national_user', 'pw'),
            'admin': self._login('admin_user', 'pw'),
        }

    def _login(self, username: str, password: str) -> str:
        res = self.client.post('/auth/login', json={'username': username, 'password': password})
        self.assertEqual(res.status_code, 200)
        return res.json()['access_token']

    def _auth_header(self, role: str):
        return {'Authorization': f"Bearer {self.tokens[role]}"}

    def test_auth_invalid_credentials(self):
        res = self.client.post('/auth/login', json={'username': 'district_user', 'password': 'bad'})
        self.assertEqual(res.status_code, 401)

    def test_metadata_endpoints(self):
        self.assertEqual(self.client.get('/metadata/states').status_code, 200)
        self.assertEqual(self.client.get('/metadata/districts').status_code, 200)
        resources = self.client.get('/metadata/resources')
        self.assertEqual(resources.status_code, 200)
        payload = resources.json()
        self.assertTrue(len(payload) > 0)
        self.assertIn('is_returnable', payload[0])
        self.assertIn('is_consumable', payload[0])
        self.assertIn('must_return_if_claimed', payload[0])

    def test_district_full_flow_endpoints(self):
        h = self._auth_header('district')

        self.assertEqual(self.client.get('/district/me', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/district/demand-mode', headers=h).status_code, 200)

        upd = self.client.put('/district/demand-mode', headers=h, json={'demand_mode': 'human_only'})
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.json()['demand_mode'], 'human_only')

        upd_alias = self.client.put('/district/demand-mode', headers=h, json={'demand_mode': 'ai_human'})
        self.assertEqual(upd_alias.status_code, 200)
        self.assertEqual(upd_alias.json()['demand_mode'], 'baseline_plus_human')

        self.assertEqual(self.client.get('/district/allocations', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/district/unmet', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/district/solver-status', headers=h).status_code, 200)

        claim = self.client.post('/district/claim', headers=h, json={'resource_id': 'water', 'time': 1, 'quantity': 20, 'claimed_by': 'ops'})
        self.assertEqual(claim.status_code, 200)
        self.assertIn('snapshot', claim.json())

        consume = self.client.post('/district/consume', headers=h, json={'resource_id': 'water', 'time': 1, 'quantity': 10})
        self.assertEqual(consume.status_code, 200)

        ret = self.client.post('/district/return', headers=h, json={'resource_id': 'water', 'time': 1, 'quantity': 5, 'reason': 'manual'})
        self.assertEqual(ret.status_code, 400)

        claim_r10 = self.client.post('/district/claim', headers=h, json={'resource_id': 'R10', 'time': 1, 'quantity': 10, 'claimed_by': 'ops'})
        self.assertEqual(claim_r10.status_code, 200)
        ret_r10 = self.client.post('/district/return', headers=h, json={'resource_id': 'R10', 'time': 1, 'quantity': 5, 'reason': 'manual'})
        self.assertEqual(ret_r10.status_code, 200)

        self.assertEqual(self.client.get('/district/claims', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/district/consumptions', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/district/returns', headers=h).status_code, 200)

        with patch('app.routers.district.create_request', return_value={'status': 'accepted', 'request_id': 999}):
            req = self.client.post('/district/request', headers=h, json={
                'resource_id': 'water',
                'time': 1,
                'quantity': 10,
                'priority': 1,
                'urgency': 1,
                'confidence': 1.0,
                'source': 'human',
            })
            self.assertEqual(req.status_code, 201)

        with patch('app.routers.district.create_request_batch', return_value={'status': 'accepted', 'request_ids': [1001, 1002], 'solver_run_id': 8}):
            req_batch = self.client.post('/district/request-batch', headers=h, json={
                'items': [
                    {
                        'resource_id': 'water',
                        'time': 1,
                        'quantity': 10,
                        'priority': 1,
                        'urgency': 1,
                        'confidence': 1.0,
                        'source': 'human',
                    },
                    {
                        'resource_id': 'food',
                        'time': 1,
                        'quantity': 5,
                        'priority': 2,
                        'urgency': 2,
                        'confidence': 0.9,
                        'source': 'human',
                    }
                ]
            })
            self.assertEqual(req_batch.status_code, 200)

        self.assertEqual(self.client.get('/district/requests', headers=h).status_code, 200)

    def test_district_allocations_use_latest_run_for_actions(self):
        h = self._auth_header('district')

        db = self.Session()
        try:
            latest = SolverRun(mode='live', status='completed')
            db.add(latest)
            db.commit()
            db.refresh(latest)

            db.add(Allocation(
                solver_run_id=int(latest.id),
                request_id=0,
                resource_id='water',
                district_code='101',
                state_code='10',
                time=2,
                allocated_quantity=60.0,
                is_unmet=False,
                claimed_quantity=0.0,
                consumed_quantity=0.0,
                returned_quantity=0.0,
                status='allocated',
            ))
            db.commit()
        finally:
            db.close()

        alloc_res = self.client.get('/district/allocations', headers=h)
        self.assertEqual(alloc_res.status_code, 200)
        rows = alloc_res.json()
        self.assertTrue(len(rows) > 0)
        run_ids = {int(r['solver_run_id']) for r in rows}
        self.assertGreaterEqual(len(run_ids), 2)
        latest_run_id = max(run_ids)

        row = next(r for r in rows if int(r['solver_run_id']) == int(latest_run_id))
        claim = self.client.post('/district/claim', headers=h, json={
            'resource_id': row['resource_id'],
            'time': int(row['time']),
            'quantity': 10,
            'claimed_by': 'ops',
        })
        self.assertEqual(claim.status_code, 200)
        self.assertEqual(int(claim.json()['snapshot']['allocated_quantity']), int(row['allocated_quantity']))
        self.assertEqual(int(claim.json()['snapshot']['claimed_quantity']), 10)

        solver_status = self.client.get('/district/solver-status', headers=h)
        self.assertEqual(solver_status.status_code, 200)
        self.assertEqual(int(solver_status.json()['solver_run_id']), int(latest_run_id))

    def test_return_for_returnable_goes_back_to_origin_pool(self):
        h = self._auth_header('district')

        db = self.Session()
        try:
            alloc = db.query(Allocation).filter(
                Allocation.resource_id == 'R10',
                Allocation.district_code == '101',
                Allocation.time == 1,
                Allocation.is_unmet == False,
            ).first()
            self.assertIsNotNone(alloc)
            alloc.origin_state = '20'
            alloc.origin_state_code = '20'
            alloc.supply_level = 'state'
            alloc.allocation_source_scope = 'state'
            alloc.allocation_source_code = '20'
            db.commit()
        finally:
            db.close()

        claim = self.client.post('/district/claim', headers=h, json={'resource_id': 'R10', 'time': 1, 'quantity': 10, 'claimed_by': 'ops'})
        self.assertEqual(claim.status_code, 200)

        ret = self.client.post('/district/return', headers=h, json={
            'resource_id': 'R10',
            'time': 1,
            'quantity': 4,
            'reason': 'manual',
            'allocation_source_scope': 'state',
            'allocation_source_code': '20',
        })
        self.assertEqual(ret.status_code, 200)

        db = self.Session()
        try:
            tx = db.query(PoolTransaction).filter(
                PoolTransaction.resource_id == 'R10',
                PoolTransaction.district_code == '101',
                PoolTransaction.reason.like('district_return_to_origin:%'),
            ).order_by(PoolTransaction.id.desc()).first()
            self.assertIsNotNone(tx)
            self.assertEqual(str(tx.state_code), '20')
            self.assertAlmostEqual(float(tx.quantity_delta), 4.0, places=6)
        finally:
            db.close()

    def test_return_with_district_source_credits_district_stock(self):
        h = self._auth_header('district')

        db = self.Session()
        try:
            alloc = db.query(Allocation).filter(
                Allocation.resource_id == 'R10',
                Allocation.district_code == '101',
                Allocation.time == 1,
                Allocation.is_unmet == False,
            ).first()
            self.assertIsNotNone(alloc)
            alloc.supply_level = 'district'
            alloc.allocation_source_scope = 'district'
            alloc.allocation_source_code = '101'
            db.commit()
        finally:
            db.close()

        claim = self.client.post('/district/claim', headers=h, json={
            'resource_id': 'R10',
            'time': 1,
            'quantity': 6,
            'claimed_by': 'ops',
        })
        self.assertEqual(claim.status_code, 200)

        ret = self.client.post('/district/return', headers=h, json={
            'resource_id': 'R10',
            'time': 1,
            'quantity': 6,
            'reason': 'manual',
            'allocation_source_scope': 'district',
            'allocation_source_code': '101',
        })
        self.assertEqual(ret.status_code, 200)

        db = self.Session()
        try:
            credit = db.query(StockRefillTransaction).filter(
                StockRefillTransaction.scope == 'district',
                StockRefillTransaction.district_code == '101',
                StockRefillTransaction.resource_id == 'R10',
                StockRefillTransaction.source == 'district_return_credit',
            ).order_by(StockRefillTransaction.id.desc()).first()
            self.assertIsNotNone(credit)
            self.assertAlmostEqual(float(credit.quantity_delta), 6.0, places=6)
        finally:
            db.close()

    def test_state_endpoints(self):
        h = self._auth_header('state')

        self.assertEqual(self.client.get('/state/me', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/state/requests', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/state/allocations', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/state/allocations/summary', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/state/unmet', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/state/escalations', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/state/pool', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/state/pool/transactions', headers=h).status_code, 200)

        esc = self.client.post('/state/escalations/1', headers=h, json={'reason': 'needs national support'})
        self.assertEqual(esc.status_code, 200)

        alloc = self.client.post('/state/pool/allocate', headers=h, json={
            'resource_id': 'R10',
            'time': 1,
            'quantity': 5,
            'target_district': '101',
            'note': 'test allocate',
        })
        self.assertEqual(alloc.status_code, 200)

    def test_phase9_mutual_aid_endpoints(self):
        district_h = self._auth_header('district')
        state_h = self._auth_header('state')

        req = self.client.post('/district/mutual-aid/request', headers=district_h, json={
            'resource_id': 'R10',
            'quantity_requested': 15,
            'time': 1,
        })
        self.assertEqual(req.status_code, 200)
        self.assertEqual(req.json().get('request_status'), 'open')

        my_req = self.client.get('/state/mutual-aid/requests', headers=state_h)
        self.assertEqual(my_req.status_code, 200)
        self.assertTrue(isinstance(my_req.json(), list))

        market_empty = self.client.get('/state/mutual-aid/market', headers=state_h)
        self.assertEqual(market_empty.status_code, 200)

        db = self.Session()
        try:
            remote_req = MutualAidRequest(
                requesting_state='20',
                requesting_district='201',
                resource_id='R10',
                quantity_requested=25.0,
                time=1,
                status='open',
            )
            db.add(remote_req)
            db.commit()
            db.refresh(remote_req)
            remote_id = int(remote_req.id)
        finally:
            db.close()

        market = self.client.get('/state/mutual-aid/market', headers=state_h)
        self.assertEqual(market.status_code, 200)
        self.assertTrue(any(int(row.get('id')) == remote_id for row in market.json()))

        offer = self.client.post('/state/mutual-aid/offers', headers=state_h, json={
            'request_id': remote_id,
            'quantity_offered': 10,
            'cap_quantity': 8,
        })
        self.assertEqual(offer.status_code, 200)
        self.assertEqual(float(offer.json().get('quantity_offered')), 8.0)

        offer_id = int(offer.json().get('offer_id'))
        revoke = self.client.post(f'/state/mutual-aid/offers/{offer_id}/respond', headers=state_h, json={
            'decision': 'revoked',
        })
        self.assertEqual(revoke.status_code, 200)
        self.assertEqual(revoke.json().get('offer_status'), 'revoked')

    def test_national_endpoints(self):
        h = self._auth_header('national')

        self.assertEqual(self.client.get('/national/me', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/national/requests', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/national/allocations', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/national/allocations/summary', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/national/unmet', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/national/allocations/stock', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/national/escalations', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/national/pool', headers=h).status_code, 200)
        self.assertEqual(self.client.get('/national/pool/10', headers=h).status_code, 200)

        resolve = self.client.post('/national/escalations/2/resolve', headers=h, json={'decision': 'allocated', 'note': 'approved'})
        self.assertEqual(resolve.status_code, 200)

        alloc = self.client.post('/national/pool/allocate', headers=h, json={
            'state_code': '10',
            'resource_id': 'R10',
            'time': 1,
            'quantity': 5,
            'target_district': '101',
            'note': 'national allocation',
        })
        self.assertEqual(alloc.status_code, 200)

    def test_admin_endpoints(self):
        h = self._auth_header('admin')

        create = self.client.post('/admin/scenarios', headers=h, json={'name': 'Scenario A'})
        self.assertEqual(create.status_code, 200)
        scenario_id = create.json()['id']

        self.assertEqual(self.client.get('/admin/scenarios', headers=h).status_code, 200)
        self.assertEqual(self.client.get(f'/admin/scenarios/{scenario_id}', headers=h).status_code, 200)

        add_demand = self.client.post(f'/admin/scenarios/{scenario_id}/add-demand', headers=h, json={
            'district_code': '101',
            'state_code': '10',
            'resource_id': 'water',
            'time': 1,
            'quantity': 20,
        })
        self.assertEqual(add_demand.status_code, 200)

        add_demand_batch = self.client.post(f'/admin/scenarios/{scenario_id}/add-demand-batch', headers=h, json={
            'rows': [
                {
                    'district_code': '101',
                    'state_code': '10',
                    'resource_id': 'food',
                    'time': 1,
                    'quantity': 10,
                }
            ]
        })
        self.assertEqual(add_demand_batch.status_code, 200)

        add_state = self.client.post(f'/admin/scenarios/{scenario_id}/set-state-stock', headers=h, json={
            'state_code': '10',
            'resource_id': 'water',
            'quantity': 100,
        })
        self.assertEqual(add_state.status_code, 200)

        add_nat = self.client.post(f'/admin/scenarios/{scenario_id}/set-national-stock', headers=h, json={
            'resource_id': 'water',
            'quantity': 200,
        })
        self.assertEqual(add_nat.status_code, 200)

        with patch('app.routers.admin.run_scenario', return_value=None):
            run = self.client.post(f'/admin/scenarios/{scenario_id}/run', headers=h, json={})
            self.assertEqual(run.status_code, 200)

        self.assertEqual(self.client.get(f'/admin/scenarios/{scenario_id}/runs', headers=h).status_code, 200)
        self.assertEqual(self.client.get(f'/admin/scenarios/{scenario_id}/analysis', headers=h).status_code, 200)
        self.assertEqual(self.client.get(f'/admin/scenarios/{scenario_id}/runs/999/summary', headers=h).status_code, 200)

    def test_role_guard_forbidden(self):
        h = self._auth_header('district')
        res = self.client.get('/admin/scenarios', headers=h)
        self.assertEqual(res.status_code, 403)

    def test_edge_invalid_quantities(self):
        h = self._auth_header('district')

        bad_claim = self.client.post('/district/claim', headers=h, json={'resource_id': 'water', 'time': 1, 'quantity': 0, 'claimed_by': 'ops'})
        self.assertEqual(bad_claim.status_code, 400)

        over_claim = self.client.post('/district/claim', headers=h, json={'resource_id': 'water', 'time': 1, 'quantity': 1000, 'claimed_by': 'ops'})
        self.assertEqual(over_claim.status_code, 400)

    def test_phase11_request_validation_and_fsm_guards(self):
        h = self._auth_header('district')

        bad_time = self.client.post('/district/request', headers=h, json={
            'resource_id': 'water',
            'time': -1,
            'quantity': 10,
            'priority': 1,
            'urgency': 1,
            'confidence': 1.0,
            'source': 'human',
        })
        self.assertEqual(bad_time.status_code, 400)
        self.assertIn('time must be >= 0', bad_time.text)

        bad_confidence = self.client.post('/district/request', headers=h, json={
            'resource_id': 'water',
            'time': 1,
            'quantity': 10,
            'priority': 1,
            'urgency': 1,
            'confidence': 1.2,
            'source': 'human',
        })
        self.assertEqual(bad_confidence.status_code, 400)
        self.assertIn('confidence must be between 0 and 1', bad_confidence.text)

        bad_decimal_countable = self.client.post('/district/request-batch', headers=h, json={
            'items': [
                {
                    'resource_id': 'R10',
                    'time': 1,
                    'quantity': 5.5,
                    'priority': 1,
                    'urgency': 1,
                    'confidence': 1.0,
                    'source': 'human',
                }
            ]
        })
        self.assertEqual(bad_decimal_countable.status_code, 400)
        self.assertIn('must be a whole number', bad_decimal_countable.text)

        consume_without_claim = self.client.post('/district/consume', headers=h, json={
            'resource_id': 'water',
            'time': 1,
            'quantity': 1,
        })
        self.assertEqual(consume_without_claim.status_code, 400)
        self.assertIn('Cannot consume', consume_without_claim.text)

        return_without_claim = self.client.post('/district/return', headers=h, json={
            'resource_id': 'R10',
            'time': 1,
            'quantity': 1,
            'reason': 'manual',
        })
        self.assertEqual(return_without_claim.status_code, 400)
        self.assertIn('Cannot return', return_without_claim.text)

    def test_non_returnable_resource_rejected_for_return(self):
        h = self._auth_header('district')

        claim = self.client.post('/district/claim', headers=h, json={'resource_id': 'water', 'time': 1, 'quantity': 8, 'claimed_by': 'ops'})
        self.assertEqual(claim.status_code, 200)

        ret = self.client.post('/district/return', headers=h, json={'resource_id': 'water', 'time': 1, 'quantity': 8, 'reason': 'manual'})
        self.assertEqual(ret.status_code, 400)
        self.assertIn('non-returnable', ret.text)

    def test_reusable_resource_cannot_be_consumed(self):
        h = self._auth_header('district')

        claim = self.client.post('/district/claim', headers=h, json={'resource_id': 'R10', 'time': 1, 'quantity': 8, 'claimed_by': 'ops'})
        self.assertEqual(claim.status_code, 200)

        consume = self.client.post('/district/consume', headers=h, json={'resource_id': 'R10', 'time': 1, 'quantity': 4})
        self.assertEqual(consume.status_code, 400)
        self.assertIn('cannot be consumed', consume.text)

    def test_request_rejects_unknown_resource_id(self):
        h = self._auth_header('district')

        res = self.client.post('/district/request', headers=h, json={
            'resource_id': 'unknown_resource_xyz',
            'time': 1,
            'quantity': 10,
            'priority': 1,
            'urgency': 1,
            'confidence': 1.0,
            'source': 'human',
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('Unknown resource_id', res.text)

    def test_request_batch_rejects_unknown_resource_id(self):
        h = self._auth_header('district')

        res = self.client.post('/district/request-batch', headers=h, json={
            'items': [
                {
                    'resource_id': 'water',
                    'time': 1,
                    'quantity': 10,
                    'priority': 1,
                    'urgency': 1,
                    'confidence': 1.0,
                    'source': 'human',
                },
                {
                    'resource_id': 'bad_alias_zzz',
                    'time': 1,
                    'quantity': 5,
                    'priority': 1,
                    'urgency': 1,
                    'confidence': 1.0,
                    'source': 'human',
                }
            ]
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('Unknown resource_id', res.text)

    def test_stress_repeated_reads_and_actions(self):
        h_d = self._auth_header('district')
        h_s = self._auth_header('state')

        for _ in range(20):
            self.assertEqual(self.client.get('/district/allocations', headers=h_d).status_code, 200)
            self.assertEqual(self.client.get('/district/unmet', headers=h_d).status_code, 200)
            self.assertEqual(self.client.get('/state/pool', headers=h_s).status_code, 200)

        claim = self.client.post('/district/claim', headers=h_d, json={'resource_id': 'water', 'time': 1, 'quantity': 10, 'claimed_by': 'stress'})
        self.assertEqual(claim.status_code, 200)

        for _ in range(10):
            self.assertEqual(self.client.get('/district/claims', headers=h_d).status_code, 200)


if __name__ == '__main__':
    unittest.main()
