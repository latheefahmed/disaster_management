from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.database import SessionLocal, apply_runtime_migrations
from app.engine_bridge.ingest import ingest_solver_results
from app.models.allocation import Allocation
from app.models.solver_run import SolverRun

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "core_engine" / "phase4" / "optimization" / "output"
ART_DIR = ROOT / "core_engine" / "phase4" / "scenarios" / "generated" / "validation_matrix"
ART_DIR.mkdir(parents=True, exist_ok=True)


def _to_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def main() -> None:
    apply_runtime_migrations()

    alloc_csv = pd.read_csv(OUT_DIR / "allocation_x.csv") if (OUT_DIR / "allocation_x.csv").exists() else pd.DataFrame()
    unmet_csv = pd.read_csv(OUT_DIR / "unmet_demand_u.csv") if (OUT_DIR / "unmet_demand_u.csv").exists() else pd.DataFrame()

    csv_alloc_count = int(len(alloc_csv.index))
    csv_unmet_count = int(len(unmet_csv.index))
    csv_alloc_sum = float(pd.to_numeric(alloc_csv.get("allocated_quantity", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    csv_unmet_sum = float(pd.to_numeric(unmet_csv.get("unmet_quantity", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())

    db = SessionLocal()
    try:
        run = SolverRun(mode="live", status="completed")
        db.add(run)
        db.commit()
        db.refresh(run)

        ingest_solver_results(db, solver_run_id=int(run.id))

        db_alloc = db.query(Allocation).filter(Allocation.solver_run_id == int(run.id), Allocation.is_unmet == False).all()
        db_unmet = db.query(Allocation).filter(Allocation.solver_run_id == int(run.id), Allocation.is_unmet == True).all()

        db_alloc_count = int(len(db_alloc))
        db_unmet_count = int(len(db_unmet))
        db_alloc_sum = float(sum(_to_float(r.allocated_quantity) for r in db_alloc))
        db_unmet_sum = float(sum(_to_float(r.allocated_quantity) for r in db_unmet))

        parity = {
            "solver_run_id": int(run.id),
            "csv": {
                "alloc_count": csv_alloc_count,
                "unmet_count": csv_unmet_count,
                "alloc_sum": csv_alloc_sum,
                "unmet_sum": csv_unmet_sum,
            },
            "db": {
                "alloc_count": db_alloc_count,
                "unmet_count": db_unmet_count,
                "alloc_sum": db_alloc_sum,
                "unmet_sum": db_unmet_sum,
            },
            "matches": {
                "alloc_count": db_alloc_count == csv_alloc_count,
                "unmet_count": db_unmet_count == csv_unmet_count,
                "alloc_sum": abs(db_alloc_sum - csv_alloc_sum) <= 1e-9,
                "unmet_sum": abs(db_unmet_sum - csv_unmet_sum) <= 1e-9,
            },
        }
        parity["all_match"] = all(parity["matches"].values())

        out_path = ART_DIR / "ingest_parity_snapshot.json"
        out_path.write_text(json.dumps(parity, indent=2), encoding="utf-8")
        print(json.dumps(parity, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
