import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.allocation import Allocation
from app.models.claim import Claim
from app.models.district import District
from app.models.mutual_aid_offer import MutualAidOffer
from app.models.mutual_aid_request import MutualAidRequest
from app.models.pool_transaction import PoolTransaction
from app.models.solver_run import SolverRun
from app.models.state import State
from app.models.state_transfer import StateTransfer
from app.services.action_service import create_return
from app.services.mutual_aid_service import (
    create_mutual_aid_request,
    create_mutual_aid_offer,
    respond_to_offer,
    build_state_stock_with_confirmed_transfers,
)


class Phase9MutualAidTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.Session()

        self.db.add_all([
            State(state_code="10", state_name="State 10", latitude=12.9, longitude=77.6),
            State(state_code="20", state_name="State 20", latitude=13.1, longitude=80.2),
            State(state_code="30", state_name="State 30", latitude=17.4, longitude=78.5),
        ])
        self.db.add(District(district_code="101", district_name="D101", state_code="10", demand_mode="baseline_plus_human"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_create_mutual_aid_request_row_exists(self):
        row = create_mutual_aid_request(
            db=self.db,
            requesting_state="10",
            requesting_district="101",
            resource_id="R10",
            quantity_requested=25.0,
            time=1,
        )
        self.assertIsNotNone(row.id)
        self.assertEqual(str(row.status), "open")

        persisted = self.db.query(MutualAidRequest).filter(MutualAidRequest.id == row.id).first()
        self.assertIsNotNone(persisted)
        self.assertEqual(float(persisted.quantity_requested), 25.0)

    def test_offers_accumulate_and_revoke_pending_when_satisfied(self):
        req = create_mutual_aid_request(self.db, "10", "101", "R10", 100.0, 1)

        offer_1 = create_mutual_aid_offer(self.db, req.id, "20", 40.0)
        offer_2 = create_mutual_aid_offer(self.db, req.id, "30", 60.0)
        offer_3 = create_mutual_aid_offer(self.db, req.id, "20", 10.0)

        a1 = respond_to_offer(self.db, offer_1.id, "accepted", actor_state="10")
        self.assertEqual(str(a1.status), "accepted")

        refreshed_req = self.db.query(MutualAidRequest).filter(MutualAidRequest.id == req.id).first()
        self.assertEqual(str(refreshed_req.status), "partially_filled")

        a2 = respond_to_offer(self.db, offer_2.id, "accepted", actor_state="10")
        self.assertEqual(str(a2.status), "accepted")

        refreshed_req = self.db.query(MutualAidRequest).filter(MutualAidRequest.id == req.id).first()
        self.assertEqual(str(refreshed_req.status), "satisfied")

        pending_after = self.db.query(MutualAidOffer).filter(MutualAidOffer.id == offer_3.id).first()
        self.assertEqual(str(pending_after.status), "revoked")

    def test_state_stock_override_uses_only_confirmed_transfers(self):
        req = create_mutual_aid_request(self.db, "10", "101", "R10", 100.0, 1)
        offer_accepted = create_mutual_aid_offer(self.db, req.id, "20", 30.0)
        offer_pending = create_mutual_aid_offer(self.db, req.id, "30", 50.0)

        respond_to_offer(self.db, offer_accepted.id, "accepted", actor_state="10")
        _ = offer_pending

        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            base_path = temp / "state_resource_stock.csv"
            out_path = temp / "state_resource_stock_with_aid.csv"

            pd.DataFrame([
                {"state_code": "10", "resource_id": "R10", "quantity": 100.0},
                {"state_code": "20", "resource_id": "R10", "quantity": 200.0},
                {"state_code": "30", "resource_id": "R10", "quantity": 300.0},
            ]).to_csv(base_path, index=False)

            written = build_state_stock_with_confirmed_transfers(self.db, base_path, out_path)
            self.assertIsNotNone(written)

            merged = pd.read_csv(out_path)
            qty_10 = float(
                merged[(merged["state_code"].astype(str) == "10") & (merged["resource_id"].astype(str) == "R10")]["quantity"].iloc[0]
            )
            self.assertEqual(qty_10, 130.0)

    def test_returnable_resource_goes_back_to_origin_state(self):
        run = SolverRun(mode="live", status="completed")
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

        self.db.add(Allocation(
            solver_run_id=run.id,
            request_id=0,
            resource_id="R10",
            district_code="101",
            state_code="10",
            origin_state="20",
            time=1,
            allocated_quantity=20.0,
            is_unmet=False,
            claimed_quantity=10.0,
            consumed_quantity=0.0,
            returned_quantity=0.0,
            status="claimed",
        ))
        self.db.add(Claim(
            solver_run_id=run.id,
            district_code="101",
            resource_id="R10",
            time=1,
            quantity=10.0,
            claimed_by="ops",
        ))
        self.db.commit()

        with patch("app.services.action_service.ENABLE_MUTUAL_AID", True):
            row, _snapshot = create_return(
                db=self.db,
                district_code="101",
                resource_id="R10",
                state_code="10",
                time=1,
                quantity=5,
                reason="manual",
            )
            self.assertIsNotNone(row.id)

        pool = self.db.query(PoolTransaction).order_by(PoolTransaction.id.desc()).first()
        self.assertIsNotNone(pool)
        self.assertEqual(str(pool.state_code), "20")

        transfer = self.db.query(StateTransfer).filter(StateTransfer.transfer_kind == "return").order_by(StateTransfer.id.desc()).first()
        self.assertIsNotNone(transfer)
        self.assertEqual(str(transfer.from_state), "10")
        self.assertEqual(str(transfer.to_state), "20")


if __name__ == "__main__":
    unittest.main()
