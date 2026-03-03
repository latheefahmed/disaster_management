from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.allocation import Allocation
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun


def _latest_completed_live_run_ids(db: Session, limit: int = 3) -> list[int]:
    rows = db.query(SolverRun).filter(
        SolverRun.mode == "live",
        SolverRun.status == "completed",
    ).order_by(SolverRun.id.desc()).limit(max(1, int(limit))).all()
    return [int(r.id) for r in rows]


def generate_signals(db: Session, now_utc: datetime | None = None) -> list[dict]:
    now = now_utc or datetime.utcnow()
    signals: list[dict] = []

    run_ids = _latest_completed_live_run_ids(db, limit=3)

    if run_ids:
        unmet_rows = db.query(Allocation).filter(
            Allocation.solver_run_id.in_(run_ids),
            Allocation.is_unmet == True,
            Allocation.allocated_quantity > 0.0,
        ).all()

        unmet_runs_by_key: dict[tuple[str, str], set[int]] = defaultdict(set)
        unmet_qty_by_key: dict[tuple[str, str], float] = defaultdict(float)
        latest_time_by_key: dict[tuple[str, str], int] = defaultdict(int)

        for row in unmet_rows:
            key = (str(row.district_code), str(row.resource_id))
            unmet_runs_by_key[key].add(int(row.solver_run_id))
            unmet_qty_by_key[key] += float(row.allocated_quantity or 0.0)
            latest_time_by_key[key] = max(latest_time_by_key[key], int(row.time or 0))

        for key, run_id_set in unmet_runs_by_key.items():
            if len(run_id_set) >= 3:
                district_code, resource_id = key
                signals.append({
                    "signal_type": "chronic_unmet",
                    "entity_type": "district",
                    "entity_id": district_code,
                    "resource_id": resource_id,
                    "severity": "high",
                    "evidence": {
                        "run_ids": sorted(list(run_id_set)),
                        "unmet_total": float(unmet_qty_by_key[key]),
                        "latest_time": int(latest_time_by_key[key]),
                    },
                })

    delayed_rows = db.query(Allocation).filter(
        Allocation.is_unmet == False,
        Allocation.receipt_confirmed == False,
        Allocation.implied_delay_hours.isnot(None),
        Allocation.implied_delay_hours > 0.0,
    ).all()

    delayed_count_by_key: dict[tuple[str, str], int] = defaultdict(int)
    delayed_examples: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in delayed_rows:
        created_at = row.created_at
        if created_at is None:
            continue
        threshold = timedelta(hours=float(row.implied_delay_hours or 0.0) * 1.5)
        if now - created_at <= threshold:
            continue
        key = (str(row.district_code), str(row.resource_id))
        delayed_count_by_key[key] += 1
        delayed_examples[key].append(int(row.id))

    for key, count in delayed_count_by_key.items():
        if count >= 2:
            district_code, resource_id = key
            signals.append({
                "signal_type": "chronic_delay",
                "entity_type": "district",
                "entity_id": district_code,
                "resource_id": resource_id,
                "severity": "medium",
                "evidence": {
                    "overdue_allocations": delayed_examples[key][:10],
                    "count": int(count),
                },
            })

    if run_ids:
        earliest_run = min(run_ids)
        earliest_run_obj = db.query(SolverRun).filter(SolverRun.id == earliest_run).first()
        if earliest_run_obj is not None and earliest_run_obj.started_at is not None:
            override_rows = db.query(ResourceRequest).filter(
                ResourceRequest.source == "human",
                ResourceRequest.created_at >= earliest_run_obj.started_at,
            ).all()

            override_count_by_district: dict[str, int] = defaultdict(int)
            for row in override_rows:
                override_count_by_district[str(row.district_code)] += 1

            for district_code, count in override_count_by_district.items():
                if count >= 3:
                    signals.append({
                        "signal_type": "repeated_override",
                        "entity_type": "district",
                        "entity_id": district_code,
                        "severity": "medium",
                        "evidence": {
                            "override_count": int(count),
                            "window_run_ids": sorted(run_ids),
                        },
                    })

    return signals
