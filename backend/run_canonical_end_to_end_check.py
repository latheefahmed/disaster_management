from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from app.database import SessionLocal, apply_runtime_migrations
from app.engine_bridge.ingest import ingest_solver_results
from app.models.allocation import Allocation
from app.models.district import District
from app.models.solver_run import SolverRun

ROOT = Path(__file__).resolve().parents[1]
SOLVER_SCRIPT = ROOT / "core_engine" / "phase4" / "optimization" / "just_runs_cbc.py"
ART_DIR = ROOT / "core_engine" / "phase4" / "scenarios" / "generated" / "validation_matrix"
ART_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    apply_runtime_migrations()

    demand = ART_DIR / "canonical_e2e_demand.csv"
    dstock = ART_DIR / "canonical_e2e_district_stock.csv"
    sstock = ART_DIR / "canonical_e2e_state_stock.csv"
    nstock = ART_DIR / "canonical_e2e_national_stock.csv"

    pd.DataFrame([
        {"district_code": "1", "resource_id": "R1", "time": 1, "demand": 10.0}
    ]).to_csv(demand, index=False)
    pd.DataFrame([
        {"district_code": "1", "resource_id": "R1", "quantity": 100.0}
    ]).to_csv(dstock, index=False)
    pd.DataFrame([
        {"state_code": "1", "resource_id": "R1", "quantity": 0.0}
    ]).to_csv(sstock, index=False)
    pd.DataFrame([
        {"resource_id": "R1", "quantity": 0.0}
    ]).to_csv(nstock, index=False)

    cmd = [
        sys.executable,
        str(SOLVER_SCRIPT),
        "--demand", str(demand),
        "--district-stock", str(dstock),
        "--state-stock", str(sstock),
        "--national-stock", str(nstock),
        "--horizon", "1",
    ]
    completed = subprocess.run(cmd, cwd=str(ROOT / "core_engine"), text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)

    db = SessionLocal()
    try:
        if db.query(District).filter(District.district_code == "1").first() is None:
            db.add(District(district_code="1", district_name="D1", state_code="1", demand_mode="baseline_plus_human"))
            db.commit()

        run = SolverRun(mode="live", status="completed")
        db.add(run)
        db.commit()
        db.refresh(run)

        ingest_solver_results(db, solver_run_id=int(run.id))

        alloc_rows = db.query(Allocation).filter(
            Allocation.solver_run_id == int(run.id),
            Allocation.district_code == "1",
            Allocation.resource_id == "R1",
            Allocation.time == 1,
        ).all()
        allocated = float(sum(float(r.allocated_quantity or 0.0) for r in alloc_rows if not bool(r.is_unmet)))
        unmet = float(sum(float(r.allocated_quantity or 0.0) for r in alloc_rows if bool(r.is_unmet)))

        district_rows = [r for r in alloc_rows if not bool(r.is_unmet) and str(r.supply_level) == "district"]

        out = {
            "solver_run_id": int(run.id),
            "allocated": allocated,
            "unmet": unmet,
            "district_alloc_rows": len(district_rows),
            "district_alloc_total": float(sum(float(r.allocated_quantity or 0.0) for r in district_rows)),
            "passes": bool(abs(allocated - 10.0) <= 1e-9 and unmet <= 1e-9 and len(district_rows) >= 1),
        }
        (ART_DIR / "canonical_e2e_snapshot.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
