from __future__ import annotations

import json
from datetime import datetime
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.allocation import Allocation
from app.models.final_demand import FinalDemand
from app.models.solver_run import SolverRun


def _jain(values: list[float]) -> float | None:
    clean = [max(0.0, float(v)) for v in values]
    if not clean:
        return None
    numerator = sum(clean) ** 2
    denominator = float(len(clean)) * sum(v * v for v in clean)
    if denominator <= 1e-12:
        return None
    return float(numerator / denominator)


def build_solver_run_snapshot(db: Session, solver_run_id: int) -> dict:
    run_id = int(solver_run_id)

    alloc_rows = db.query(
        Allocation.state_code,
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("allocated_quantity"),
    ).filter(
        Allocation.solver_run_id == run_id,
        Allocation.is_unmet == False,
    ).group_by(
        Allocation.state_code,
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    unmet_rows = db.query(
        Allocation.state_code,
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("unmet_quantity"),
    ).filter(
        Allocation.solver_run_id == run_id,
        Allocation.is_unmet == True,
    ).group_by(
        Allocation.state_code,
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    final_rows = db.query(
        FinalDemand.state_code,
        FinalDemand.district_code,
        FinalDemand.resource_id,
        FinalDemand.time,
        func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0).label("final_demand_quantity"),
    ).filter(
        FinalDemand.solver_run_id == run_id,
    ).group_by(
        FinalDemand.state_code,
        FinalDemand.district_code,
        FinalDemand.resource_id,
        FinalDemand.time,
    ).all()

    scope_rows = db.query(
        func.coalesce(Allocation.allocation_source_scope, "").label("scope"),
        func.coalesce(Allocation.supply_level, "district").label("level"),
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("quantity"),
    ).filter(
        Allocation.solver_run_id == run_id,
        Allocation.is_unmet == False,
    ).group_by(
        Allocation.allocation_source_scope,
        Allocation.supply_level,
    ).all()

    unmet_map = {
        (str(r.state_code or ""), str(r.district_code or ""), str(r.resource_id or ""), int(r.time)): float(r.unmet_quantity or 0.0)
        for r in unmet_rows
    }
    final_map = {
        (str(r.state_code or ""), str(r.district_code or ""), str(r.resource_id or ""), int(r.time)): float(r.final_demand_quantity or 0.0)
        for r in final_rows
    }

    national_rows: list[dict] = []
    state_summary_rows: list[dict] = []
    by_time_alloc: dict[int, float] = defaultdict(float)
    by_time_unmet: dict[int, float] = defaultdict(float)
    by_state_alloc: dict[str, float] = defaultdict(float)
    by_state_unmet: dict[str, float] = defaultdict(float)
    by_district_alloc: dict[str, float] = defaultdict(float)
    by_district_unmet: dict[str, float] = defaultdict(float)

    consistent_count = 0
    for row in alloc_rows:
        key = (str(row.state_code or ""), str(row.district_code or ""), str(row.resource_id or ""), int(row.time))
        allocated_val = float(row.allocated_quantity or 0.0)
        unmet_val = float(unmet_map.get(key, 0.0))
        final_val = float(final_map.get(key, 0.0))
        consistent = abs((allocated_val + unmet_val) - final_val) <= 1e-6
        if consistent:
            consistent_count += 1

        state_code = str(row.state_code or "")
        district_code = str(row.district_code or "")
        time_idx = int(row.time)

        national_rows.append(
            {
                "solver_run_id": run_id,
                "state_code": state_code,
                "district_code": district_code,
                "resource_id": str(row.resource_id),
                "time": time_idx,
                "allocated_quantity": allocated_val,
                "unmet_quantity": unmet_val,
                "final_demand_quantity": final_val,
                "met": unmet_val <= 1e-9,
                "lineage_consistent": bool(consistent),
            }
        )

        state_summary_rows.append(
            {
                "solver_run_id": run_id,
                "district_code": district_code,
                "resource_id": str(row.resource_id),
                "time": time_idx,
                "allocated_quantity": allocated_val,
                "unmet_quantity": unmet_val,
                "final_demand_quantity": final_val,
                "met": unmet_val <= 1e-9,
                "lineage_consistent": bool(consistent),
                "state_code": state_code,
            }
        )

        by_time_alloc[time_idx] += allocated_val
        by_time_unmet[time_idx] += unmet_val
        by_state_alloc[state_code] += allocated_val
        by_state_unmet[state_code] += unmet_val
        by_district_alloc[district_code] += allocated_val
        by_district_unmet[district_code] += unmet_val

    totals_alloc = float(sum(by_district_alloc.values()))
    totals_unmet = float(sum(by_district_unmet.values()))
    totals_final = totals_alloc + totals_unmet
    coverage = (totals_alloc / totals_final) if totals_final > 0.0 else 0.0

    scope_allocations = {
        "district": 0.0,
        "state": 0.0,
        "neighbor_state": 0.0,
        "national": 0.0,
    }
    for row in scope_rows:
        raw_scope = str(row.scope or "").strip().lower()
        raw_level = str(row.level or "district").strip().lower()
        key = raw_scope if raw_scope in scope_allocations else raw_level
        if key not in scope_allocations:
            key = "district"
        scope_allocations[key] += float(row.quantity or 0.0)

    district_service_ratios = [
        float(by_district_alloc.get(d, 0.0)) / float(by_district_alloc.get(d, 0.0) + by_district_unmet.get(d, 0.0))
        for d in sorted(set(list(by_district_alloc.keys()) + list(by_district_unmet.keys())))
        if float(by_district_alloc.get(d, 0.0) + by_district_unmet.get(d, 0.0)) > 1e-9
    ]
    state_service_ratios = [
        float(by_state_alloc.get(s, 0.0)) / float(by_state_alloc.get(s, 0.0) + by_state_unmet.get(s, 0.0))
        for s in sorted(set(list(by_state_alloc.keys()) + list(by_state_unmet.keys())))
        if float(by_state_alloc.get(s, 0.0) + by_state_unmet.get(s, 0.0)) > 1e-9
    ]

    district_jain = _jain(district_service_ratios)
    state_jain = _jain(state_service_ratios)
    district_gap = (max(district_service_ratios) - min(district_service_ratios)) if district_service_ratios else None
    state_gap = (max(state_service_ratios) - min(state_service_ratios)) if state_service_ratios else None

    by_time = []
    for t in sorted(set(list(by_time_alloc.keys()) + list(by_time_unmet.keys()))):
        met = float(by_time_alloc.get(t, 0.0))
        unmet = float(by_time_unmet.get(t, 0.0))
        demand = met + unmet
        by_time.append(
            {
                "time": int(t),
                "allocated_quantity": met,
                "unmet_quantity": unmet,
                "demand_quantity": demand,
                "service_ratio": (met / demand) if demand > 1e-9 else 1.0,
            }
        )

    return {
        "version": 1,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "solver_run_id": run_id,
        "totals": {
            "allocated_quantity": totals_alloc,
            "unmet_quantity": totals_unmet,
            "final_demand_quantity": totals_final,
            "coverage": coverage,
            "districts_covered": len(by_district_alloc.keys() | by_district_unmet.keys()),
            "lineage_consistent_rows": int(consistent_count),
            "lineage_total_rows": int(len(national_rows)),
        },
        "source_scope_breakdown": {
            "allocations": {k: float(v) for k, v in scope_allocations.items()},
            "percentages": {
                k: float((v / sum(scope_allocations.values())) if sum(scope_allocations.values()) > 1e-9 else 0.0)
                for k, v in scope_allocations.items()
            },
        },
        "fairness": {
            "district_ratio_jain": district_jain,
            "state_ratio_jain": state_jain,
            "district_ratio_gap": district_gap,
            "state_ratio_gap": state_gap,
        },
        "by_time_breakdown": by_time,
        "state_allocation_summary_rows": state_summary_rows,
        "national_allocation_summary_rows": national_rows,
        "district_totals": {
            district: {
                "allocated_quantity": float(by_district_alloc.get(district, 0.0)),
                "unmet_quantity": float(by_district_unmet.get(district, 0.0)),
            }
            for district in sorted(set(list(by_district_alloc.keys()) + list(by_district_unmet.keys())))
        },
        "state_totals": {
            state: {
                "allocated_quantity": float(by_state_alloc.get(state, 0.0)),
                "unmet_quantity": float(by_state_unmet.get(state, 0.0)),
            }
            for state in sorted(set(list(by_state_alloc.keys()) + list(by_state_unmet.keys())))
        },
    }


def persist_solver_run_snapshot(db: Session, solver_run_id: int) -> dict:
    snapshot = build_solver_run_snapshot(db, int(solver_run_id))
    run = db.query(SolverRun).filter(SolverRun.id == int(solver_run_id)).first()
    if run is not None:
        run.summary_snapshot_json = json.dumps(snapshot, separators=(",", ":"))
    return snapshot
