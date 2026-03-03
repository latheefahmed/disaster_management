import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.engine_bridge.ingest import ingest_solver_results
from app.models.district import District
from app.models.solver_run import SolverRun
from app.models.inventory_snapshot import InventorySnapshot
from app.models.shipment_plan import ShipmentPlan


class Phase8MultiPeriodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.script = cls.repo_root / "core_engine" / "phase4" / "optimization" / "just_runs_cbc.py"
        cls.output_dir = cls.repo_root / "core_engine" / "phase4" / "optimization" / "output"

    def _write_csv(self, path: Path, rows: list[dict], columns: list[str]):
        pd.DataFrame(rows, columns=columns).to_csv(path, index=False)

    def _run_solver(self, demand_path: Path, district_stock_path: Path, state_stock_path: Path, national_stock_path: Path, horizon: int, rolling: bool = False):
        cmd = [
            sys.executable,
            str(self.script),
            "--demand",
            str(demand_path),
            "--district-stock",
            str(district_stock_path),
            "--state-stock",
            str(state_stock_path),
            "--national-stock",
            str(national_stock_path),
            "--horizon",
            str(horizon),
        ]
        if rolling:
            cmd.append("--rolling")

        subprocess.run(cmd, check=True, cwd=str(self.repo_root))

    def test_phase8_inventory_balance_and_deterministic_repeatability(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            demand_path = temp / "demand.csv"
            district_stock_path = temp / "district_stock.csv"
            state_stock_path = temp / "state_stock.csv"
            national_stock_path = temp / "national_stock.csv"

            self._write_csv(
                demand_path,
                [
                    {"district_code": "1", "resource_id": "R1", "time": 1, "demand": 0.2},
                    {"district_code": "1", "resource_id": "R1", "time": 2, "demand": 0.0},
                    {"district_code": "1", "resource_id": "R1", "time": 3, "demand": 0.0},
                    {"district_code": "2", "resource_id": "R1", "time": 1, "demand": 0.0},
                    {"district_code": "2", "resource_id": "R1", "time": 2, "demand": 0.6},
                    {"district_code": "2", "resource_id": "R1", "time": 3, "demand": 0.0},
                ],
                ["district_code", "resource_id", "time", "demand"],
            )

            self._write_csv(
                district_stock_path,
                [
                    {"district_code": "1", "resource_id": "R1", "quantity": 120000.0},
                    {"district_code": "2", "resource_id": "R1", "quantity": 0.0},
                ],
                ["district_code", "resource_id", "quantity"],
            )
            self._write_csv(
                state_stock_path,
                [{"state_code": "1", "resource_id": "R1", "quantity": 0.0}],
                ["state_code", "resource_id", "quantity"],
            )
            self._write_csv(
                national_stock_path,
                [{"resource_id": "R1", "quantity": 0.0}],
                ["resource_id", "quantity"],
            )

            self._run_solver(demand_path, district_stock_path, state_stock_path, national_stock_path, horizon=3, rolling=False)

            alloc_1 = pd.read_csv(self.output_dir / "allocation_x.csv")
            unmet_1 = pd.read_csv(self.output_dir / "unmet_u.csv")
            inv_1 = pd.read_csv(self.output_dir / "inventory_t.csv")
            ship_1 = pd.read_csv(self.output_dir / "shipment_plan.csv")
            summary_1 = json.loads((self.output_dir / "run_summary.json").read_text(encoding="utf-8"))

            self.assertEqual(summary_1.get("horizon"), 3)
            self.assertFalse(summary_1.get("rolling"))

            self.assertTrue((inv_1["quantity"] >= 0).all())

            alloc_map = {
                (str(r.district_code), str(r.resource_id), int(r.time)): float(r.allocated_quantity)
                for r in alloc_1.itertuples(index=False)
            }
            ship_map = {
                (str(r.from_district), str(r.to_district), str(r.resource_id), int(r.time)): float(r.quantity)
                for r in ship_1.itertuples(index=False)
            }
            inv_map = {
                (str(r.district_code), str(r.resource_id), int(r.time)): float(r.quantity)
                for r in inv_1.itertuples(index=False)
            }

            for d in ["1", "2"]:
                for t in [1, 2, 3]:
                    inbound = sum(q for (f, to, r, tt), q in ship_map.items() if to == d and r == "R1" and tt == t and not str(f).startswith("STATE::") and str(f) != "NATIONAL")
                    outbound = sum(q for (f, to, r, tt), q in ship_map.items() if f == d and r == "R1" and tt == t and not str(f).startswith("STATE::") and str(f) != "NATIONAL")
                    alloc = float(alloc_map.get((d, "R1", t), 0.0))
                    inv_t = float(inv_map.get((d, "R1", t), 0.0))
                    inv_next = float(inv_map.get((d, "R1", t + 1), 0.0))

                    self.assertAlmostEqual(inv_next, inv_t + inbound - outbound - alloc, places=4)

            self._run_solver(demand_path, district_stock_path, state_stock_path, national_stock_path, horizon=3, rolling=False)

            alloc_2 = pd.read_csv(self.output_dir / "allocation_x.csv")
            unmet_2 = pd.read_csv(self.output_dir / "unmet_u.csv")
            inv_2 = pd.read_csv(self.output_dir / "inventory_t.csv")
            ship_2 = pd.read_csv(self.output_dir / "shipment_plan.csv")
            summary_2 = json.loads((self.output_dir / "run_summary.json").read_text(encoding="utf-8"))

            pd.testing.assert_frame_equal(
                alloc_1.sort_values(list(alloc_1.columns)).reset_index(drop=True),
                alloc_2.sort_values(list(alloc_2.columns)).reset_index(drop=True),
                check_like=True,
            )
            pd.testing.assert_frame_equal(
                unmet_1.sort_values(list(unmet_1.columns)).reset_index(drop=True),
                unmet_2.sort_values(list(unmet_2.columns)).reset_index(drop=True),
                check_like=True,
            )
            pd.testing.assert_frame_equal(
                inv_1.sort_values(list(inv_1.columns)).reset_index(drop=True),
                inv_2.sort_values(list(inv_2.columns)).reset_index(drop=True),
                check_like=True,
            )
            pd.testing.assert_frame_equal(
                ship_1.sort_values(list(ship_1.columns)).reset_index(drop=True),
                ship_2.sort_values(list(ship_2.columns)).reset_index(drop=True),
                check_like=True,
            )
            self.assertEqual(summary_1["objective"], summary_2["objective"])

    def test_phase8_rolling_horizon_executes_and_exports(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            demand_path = temp / "demand.csv"
            district_stock_path = temp / "district_stock.csv"
            state_stock_path = temp / "state_stock.csv"
            national_stock_path = temp / "national_stock.csv"

            self._write_csv(
                demand_path,
                [
                    {"district_code": "1", "resource_id": "R1", "time": 1, "demand": 0.1},
                    {"district_code": "1", "resource_id": "R1", "time": 2, "demand": 0.1},
                    {"district_code": "1", "resource_id": "R1", "time": 3, "demand": 0.1},
                ],
                ["district_code", "resource_id", "time", "demand"],
            )
            self._write_csv(
                district_stock_path,
                [{"district_code": "1", "resource_id": "R1", "quantity": 50000.0}],
                ["district_code", "resource_id", "quantity"],
            )
            self._write_csv(
                state_stock_path,
                [{"state_code": "1", "resource_id": "R1", "quantity": 0.0}],
                ["state_code", "resource_id", "quantity"],
            )
            self._write_csv(
                national_stock_path,
                [{"resource_id": "R1", "quantity": 0.0}],
                ["resource_id", "quantity"],
            )

            self._run_solver(demand_path, district_stock_path, state_stock_path, national_stock_path, horizon=2, rolling=True)
            summary = json.loads((self.output_dir / "run_summary.json").read_text(encoding="utf-8"))

            self.assertTrue(summary.get("rolling"))
            self.assertEqual(summary.get("horizon"), 2)

            alloc = pd.read_csv(self.output_dir / "allocation_x.csv")
            self.assertTrue(len(alloc.index) >= 1)

    def test_ingest_persists_inventory_and_shipment_artifacts(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=engine)
        db = Session()

        try:
            db.add(District(district_code="1", district_name="D1", state_code="1", demand_mode="baseline_plus_human"))
            db.commit()

            with patch("app.engine_bridge.ingest.parse_allocations", return_value=[]), \
                 patch("app.engine_bridge.ingest.parse_unmet", return_value=[]), \
                 patch("app.engine_bridge.ingest.parse_inventory_snapshots", return_value=[
                     {"district_code": "1", "resource_id": "R1", "time": 1, "quantity": 42.0}
                 ]), \
                 patch("app.engine_bridge.ingest.parse_shipment_plan", return_value=[
                     {
                         "from_district": "1",
                         "to_district": "2",
                         "resource_id": "R1",
                         "time": 1,
                         "quantity": 7.0,
                         "status": "planned",
                     }
                 ]):
                ingest_solver_results(db, solver_run_id=501)

            inv_rows = db.query(InventorySnapshot).filter(InventorySnapshot.solver_run_id == 501).all()
            ship_rows = db.query(ShipmentPlan).filter(ShipmentPlan.solver_run_id == 501).all()

            self.assertEqual(len(inv_rows), 1)
            self.assertEqual(len(ship_rows), 1)
            self.assertEqual(float(inv_rows[0].quantity), 42.0)
            self.assertEqual(str(ship_rows[0].status), "planned")
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
