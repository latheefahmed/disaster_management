from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.district import District
from app.models.request import ResourceRequest
from app.models.resource import Resource
from app.models.solver_run import SolverRun
from app.models.state import State
from app.models.allocation import Allocation
from app.services import request_service


def main():
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    request_service.SessionLocal = Session

    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        baseline_path = temp_dir / 'baseline.csv'
        live_demand_path = temp_dir / 'live_demand.csv'

        pd.DataFrame([
            {'district_code': '603', 'resource_id': 'water_liters', 'time': 1, 'demand': 25.0},
            {'district_code': '603', 'resource_id': 'medical_kits', 'time': 1, 'demand': 10.0},
        ]).to_csv(baseline_path, index=False)

        request_service.BASELINE_PATH = str(baseline_path)
        request_service.LIVE_DEMAND_PATH = str(live_demand_path)

        db = Session()
        try:
            db.add(State(state_code='33', state_name='Tamil Nadu'))
            db.add(District(district_code='603', district_name='Chennai', state_code='33', demand_mode='baseline_plus_human'))
            db.add(Resource(resource_id='water_liters', resource_name='Water (liters)', ethical_priority=1.0))
            db.add(Resource(resource_id='medical_kits', resource_name='Medical Kits', ethical_priority=2.0))
            db.commit()

            user = {'district_code': '603', 'state_code': '33'}

            result = request_service.create_request_batch(
                db,
                user,
                [
                    {
                        'resource_id': 'water',
                        'time': 1,
                        'quantity': 50,
                        'priority': 1,
                        'urgency': 2,
                        'confidence': 1.0,
                        'source': 'human',
                    },
                    {
                        'resource_id': 'medical_kits',
                        'time': 1,
                        'quantity': 5,
                        'priority': 2,
                        'urgency': 2,
                        'confidence': 0.9,
                        'source': 'human',
                    },
                ],
            )

            run_id = int(result['solver_run_id'])

            timeout_s = 60
            start = time.time()
            status = 'running'
            while time.time() - start < timeout_s:
                row = db.query(SolverRun).filter(SolverRun.id == run_id).first()
                if row:
                    status = row.status
                    if status in {'completed', 'failed'}:
                        break
                time.sleep(0.5)
                db.expire_all()

            alloc_rows = db.query(Allocation).filter(Allocation.solver_run_id == run_id).all()
            req_rows = db.query(ResourceRequest).order_by(ResourceRequest.id.asc()).all()

            pending = sum(1 for r in req_rows if r.status == 'pending')
            solving = sum(1 for r in req_rows if r.status == 'solving')
            allocated = sum(1 for r in req_rows if r.status in {'allocated', 'partial', 'unmet'})

            passed = (
                status == 'completed'
                and len(alloc_rows) > 0
                and pending == 0
                and solving == 0
                and allocated > 0
            )

            print('=== MANUAL DISTRICT REQUEST VALIDATION ===')
            print(f'run_id={run_id} status={status} allocations={len(alloc_rows)} requests={len(req_rows)}')
            print(f'status_counts: pending={pending} solving={solving} resolved_like={allocated}')
            print(f'PASS={passed}')

        finally:
            db.close()


if __name__ == '__main__':
    main()
