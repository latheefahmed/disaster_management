from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.database import SessionLocal, apply_runtime_migrations
from app.models.allocation import Allocation
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.services.allocation_service import confirm_allocation_receipt
from app.services.request_service import escalate_request_to_national, merge_baseline_and_human

ROOT = Path(__file__).resolve().parents[1]
ART_DIR = ROOT / "core_engine" / "phase4" / "scenarios" / "generated" / "validation_matrix"
ART_DIR.mkdir(parents=True, exist_ok=True)


def _as_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def main() -> None:
    apply_runtime_migrations()
    db = SessionLocal()
    created_request_id = None
    created_allocation_id = None
    try:
        baseline = pd.DataFrame([
            {"district_code": "101", "resource_id": "R1", "time": 1, "demand": 10.0},
            {"district_code": "101", "resource_id": "R1", "time": 2, "demand": 20.0},
        ])
        human = pd.DataFrame([
            {"district_code": "101", "resource_id": "R1", "time": 1, "demand": 5.0},
            {"district_code": "101", "resource_id": "R1", "time": 2, "demand": 10.0},
        ])
        merged, _model_ids = merge_baseline_and_human(db, baseline, human)
        merged_total = float(pd.to_numeric(merged["demand"], errors="coerce").fillna(0.0).sum())

        req = ResourceRequest(
            district_code="101",
            state_code="10",
            resource_id="R1",
            time=1,
            quantity=25.0,
            priority=3,
            urgency=3,
            confidence=1.0,
            source="human",
            status="pending",
            included_in_run=1,
            queued=0,
            created_at=datetime.utcnow(),
        )
        db.add(req)
        db.commit()
        db.refresh(req)
        created_request_id = int(req.id)

        alloc_before = int(db.query(Allocation).count())
        escalate_request_to_national(db, request_id=int(req.id), actor_state="10", reason="semantics-check")
        alloc_after = int(db.query(Allocation).count())

        run = SolverRun(mode="live", status="completed")
        db.add(run)
        db.commit()
        db.refresh(run)

        alloc = Allocation(
            solver_run_id=int(run.id),
            request_id=0,
            supply_level="state",
            resource_id="R1",
            district_code="101",
            state_code="10",
            origin_state="10",
            origin_state_code="10",
            origin_district_code=None,
            time=1,
            allocated_quantity=12.0,
            implied_delay_hours=2.5,
            receipt_confirmed=False,
            receipt_time=None,
            is_unmet=False,
            status="allocated",
        )
        db.add(alloc)
        db.commit()
        db.refresh(alloc)
        created_allocation_id = int(alloc.id)

        updated = confirm_allocation_receipt(db, allocation_id=int(alloc.id), district_code="101")

        out = {
            "merge": {
                "rows": int(len(merged.index)),
                "merged_total_demand": merged_total,
                "has_nonzero": bool((merged["demand"] > 0).any()),
            },
            "escalation": {
                "request_id": int(req.id),
                "status_after": str(db.query(ResourceRequest).filter(ResourceRequest.id == int(req.id)).first().status),
                "allocation_count_before": alloc_before,
                "allocation_count_after": alloc_after,
                "direct_allocation_side_effect": bool(alloc_after != alloc_before),
            },
            "receipt": {
                "allocation_id": int(updated.id),
                "receipt_confirmed": bool(updated.receipt_confirmed),
                "receipt_time_present": updated.receipt_time is not None,
            },
        }

        out_path = ART_DIR / "pipeline_semantics_snapshot.json"
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
    finally:
        if created_allocation_id is not None:
            db.query(Allocation).filter(Allocation.id == int(created_allocation_id)).delete()
            db.commit()
        if created_request_id is not None:
            db.query(ResourceRequest).filter(ResourceRequest.id == int(created_request_id)).delete()
            db.commit()
        db.close()


if __name__ == "__main__":
    main()
