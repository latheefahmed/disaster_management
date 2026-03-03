import csv
import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.allocation import Allocation
from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.inventory_snapshot import InventorySnapshot
from app.models.resource import Resource
from app.models.scenario import Scenario
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.shipment_plan import ShipmentPlan
from app.models.solver_run import SolverRun
from app.models.pool_transaction import PoolTransaction
from app.config import PHASE4_RESOURCE_DATA
from app.services.canonical_resources import CANONICAL_RESOURCE_ORDER
from app.services.canonical_resources import canonicalize_resource_id
from app.services.stock_refill_service import get_refill_adjustment_maps


def get_latest_solver_run_id(db: Session) -> int | None:
    candidates = [
        int(r[0])
        for r in db.query(SolverRun.id)
        .filter(
            SolverRun.status == "completed",
            SolverRun.mode == "live",
        )
        .order_by(SolverRun.id.desc())
        .all()
    ]
    if not candidates:
        return None

    final_counts = {
        int(r.solver_run_id): int(r.cnt or 0)
        for r in db.query(
            FinalDemand.solver_run_id,
            func.count(FinalDemand.id).label("cnt"),
        ).group_by(FinalDemand.solver_run_id).all()
    }
    alloc_counts = {
        int(r.solver_run_id): int(r.cnt or 0)
        for r in db.query(
            Allocation.solver_run_id,
            func.count(Allocation.id).label("cnt"),
        ).group_by(Allocation.solver_run_id).all()
    }

    for run_id in candidates:
        if final_counts.get(run_id, 0) > 0:
            return run_id
    for run_id in candidates:
        if alloc_counts.get(run_id, 0) > 0:
            return run_id
    return int(candidates[0])


def _completed_run_ids_with_signal(db: Session) -> list[int]:
    completed = [
        int(r[0])
        for r in db.query(SolverRun.id)
        .filter(
            SolverRun.status == "completed",
            SolverRun.mode == "live",
        )
        .order_by(SolverRun.id.asc())
        .all()
    ]
    if not completed:
        return []

    final_counts = {
        int(r.solver_run_id): int(r.cnt or 0)
        for r in db.query(
            FinalDemand.solver_run_id,
            func.count(FinalDemand.id).label("cnt"),
        ).group_by(FinalDemand.solver_run_id).all()
    }
    alloc_counts = {
        int(r.solver_run_id): int(r.cnt or 0)
        for r in db.query(
            Allocation.solver_run_id,
            func.count(Allocation.id).label("cnt"),
        ).group_by(Allocation.solver_run_id).all()
    }

    return [
        run_id for run_id in completed
        if final_counts.get(run_id, 0) > 0 or alloc_counts.get(run_id, 0) > 0
    ]


def _sum_allocations(db: Session, run_ids: list[int], allocation_filters: list, final_demand_filters: list):
    if not run_ids:
        return {
            "solver_run_id": None,
            "allocated": 0.0,
            "unmet": 0.0,
            "final_demand": 0.0,
            "coverage": 0.0,
        }

    latest_run_id = int(max(run_ids))

    allocated = db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
        Allocation.solver_run_id.in_(run_ids),
        Allocation.is_unmet == False,
        *allocation_filters,
    ).scalar() or 0.0

    unmet = db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
        Allocation.solver_run_id.in_(run_ids),
        Allocation.is_unmet == True,
        *allocation_filters,
    ).scalar() or 0.0

    expected_final_demand = db.query(func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0)).filter(
        FinalDemand.solver_run_id.in_(run_ids),
        *final_demand_filters,
    ).scalar() or 0.0
    final_demand_rows = db.query(FinalDemand.id).filter(
        FinalDemand.solver_run_id.in_(run_ids),
        *final_demand_filters,
    ).count()

    allocated_val = float(allocated)
    unmet_val = float(unmet)
    final_demand = float(expected_final_demand or 0.0)
    if final_demand_rows <= 0:
        final_demand = float(allocated_val + unmet_val)

    coverage = (allocated_val / final_demand) if final_demand > 0 else 0.0

    return {
        "solver_run_id": latest_run_id,
        "allocated": allocated_val,
        "unmet": unmet_val,
        "final_demand": final_demand,
        "coverage": coverage,
    }


def _snapshot_for_run(run: SolverRun) -> dict | None:
    raw = getattr(run, "summary_snapshot_json", None)
    if not raw:
        return None
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _sum_allocations_from_snapshots(db: Session, run_ids: list[int], *, district_code: str | None = None, state_code: str | None = None):
    if not run_ids:
        return None
    runs = db.query(SolverRun).filter(SolverRun.id.in_([int(x) for x in run_ids])).all()
    snapshots = {int(r.id): _snapshot_for_run(r) for r in runs}
    if not any(snapshots.values()):
        return None

    allocated = 0.0
    unmet = 0.0
    latest_run_id = int(max(run_ids))
    for run_id in run_ids:
        snap = snapshots.get(int(run_id)) or {}
        if district_code is not None:
            totals = (snap.get("district_totals") or {}).get(str(district_code)) or {}
            allocated += float(totals.get("allocated_quantity") or 0.0)
            unmet += float(totals.get("unmet_quantity") or 0.0)
        elif state_code is not None:
            totals = (snap.get("state_totals") or {}).get(str(state_code)) or {}
            allocated += float(totals.get("allocated_quantity") or 0.0)
            unmet += float(totals.get("unmet_quantity") or 0.0)
        else:
            totals = snap.get("totals") or {}
            allocated += float(totals.get("allocated_quantity") or 0.0)
            unmet += float(totals.get("unmet_quantity") or 0.0)

    final_demand = allocated + unmet
    coverage = (allocated / final_demand) if final_demand > 0.0 else 0.0
    return {
        "solver_run_id": latest_run_id,
        "allocated": float(allocated),
        "unmet": float(unmet),
        "final_demand": float(final_demand),
        "coverage": float(coverage),
    }


def compute_district_kpis(db: Session, district_code: str):
    run = db.query(SolverRun).filter(SolverRun.status == "completed", SolverRun.mode == "live").order_by(SolverRun.id.desc()).first()
    if run is None:
        return {
            "solver_run_id": None,
            "allocated": 0.0,
            "unmet": 0.0,
            "final_demand": 0.0,
            "coverage": 0.0,
        }
    snap = _snapshot_for_run(run)
    if not snap:
        return {
            "solver_run_id": int(run.id),
            "allocated": 0.0,
            "unmet": 0.0,
            "final_demand": 0.0,
            "coverage": 0.0,
        }
    totals = (snap.get("district_totals") or {}).get(str(district_code)) or {}
    allocated = float(totals.get("allocated_quantity") or 0.0)
    unmet = float(totals.get("unmet_quantity") or 0.0)
    final_demand = allocated + unmet
    coverage = (allocated / final_demand) if final_demand > 0 else 0.0
    return {
        "solver_run_id": int(run.id),
        "allocated": allocated,
        "unmet": unmet,
        "final_demand": final_demand,
        "coverage": coverage,
    }


def compute_state_kpis(db: Session, state_code: str):
    run = db.query(SolverRun).filter(SolverRun.status == "completed", SolverRun.mode == "live").order_by(SolverRun.id.desc()).first()
    if run is None:
        return {
            "solver_run_id": None,
            "allocated": 0.0,
            "unmet": 0.0,
            "final_demand": 0.0,
            "coverage": 0.0,
        }
    snap = _snapshot_for_run(run)
    if not snap:
        return {
            "solver_run_id": int(run.id),
            "allocated": 0.0,
            "unmet": 0.0,
            "final_demand": 0.0,
            "coverage": 0.0,
        }
    totals = (snap.get("state_totals") or {}).get(str(state_code)) or {}
    allocated = float(totals.get("allocated_quantity") or 0.0)
    unmet = float(totals.get("unmet_quantity") or 0.0)
    final_demand = allocated + unmet
    coverage = (allocated / final_demand) if final_demand > 0 else 0.0
    return {
        "solver_run_id": int(run.id),
        "allocated": allocated,
        "unmet": unmet,
        "final_demand": final_demand,
        "coverage": coverage,
    }


def compute_national_kpis(db: Session):
    run = db.query(SolverRun).filter(SolverRun.status == "completed", SolverRun.mode == "live").order_by(SolverRun.id.desc()).first()
    if run is None:
        return {
            "solver_run_id": None,
            "allocated": 0.0,
            "unmet": 0.0,
            "final_demand": 0.0,
            "coverage": 0.0,
        }
    snap = _snapshot_for_run(run)
    if not snap:
        return {
            "solver_run_id": int(run.id),
            "allocated": 0.0,
            "unmet": 0.0,
            "final_demand": 0.0,
            "coverage": 0.0,
        }
    totals = snap.get("totals") or {}
    allocated = float(totals.get("allocated_quantity") or 0.0)
    unmet = float(totals.get("unmet_quantity") or 0.0)
    final_demand = float(totals.get("final_demand_quantity") or (allocated + unmet))
    coverage = (allocated / final_demand) if final_demand > 0 else 0.0
    return {
        "solver_run_id": int(run.id),
        "allocated": allocated,
        "unmet": unmet,
        "final_demand": final_demand,
        "coverage": coverage,
    }


def compute_district_kpis_latest(db: Session, district_code: str):
    latest_run_id = get_latest_solver_run_id(db)
    if latest_run_id is None:
        return {
            "solver_run_id": None,
            "allocated": 0.0,
            "unmet": 0.0,
            "final_demand": 0.0,
            "coverage": 0.0,
        }
    return _sum_allocations(
        db,
        [int(latest_run_id)],
        [Allocation.district_code == str(district_code)],
        [FinalDemand.district_code == str(district_code)],
    )


def compute_state_kpis_latest(db: Session, state_code: str):
    latest_run_id = get_latest_solver_run_id(db)
    if latest_run_id is None:
        return {
            "solver_run_id": None,
            "allocated": 0.0,
            "unmet": 0.0,
            "final_demand": 0.0,
            "coverage": 0.0,
        }
    return _sum_allocations(
        db,
        [int(latest_run_id)],
        [Allocation.state_code == str(state_code)],
        [FinalDemand.state_code == str(state_code)],
    )


def compute_national_kpis_latest(db: Session):
    latest_run_id = get_latest_solver_run_id(db)
    if latest_run_id is None:
        return {
            "solver_run_id": None,
            "allocated": 0.0,
            "unmet": 0.0,
            "final_demand": 0.0,
            "coverage": 0.0,
        }
    return _sum_allocations(db, [int(latest_run_id)], [], [])


def _latest_scenario_id(db: Session) -> int | None:
    row = db.query(Scenario.id).order_by(Scenario.id.desc()).first()
    return None if row is None else int(row[0])


def _state_stock_map(db: Session, scenario_id: int | None, state_code: str | None = None) -> dict[str, float]:
    if scenario_id is None:
        return {}
    query = db.query(
        ScenarioStateStock.resource_id,
        func.coalesce(func.sum(ScenarioStateStock.quantity), 0.0).label("quantity"),
    ).filter(ScenarioStateStock.scenario_id == int(scenario_id))
    if state_code is not None:
        query = query.filter(ScenarioStateStock.state_code == str(state_code))
    rows = query.group_by(ScenarioStateStock.resource_id).all()
    out: dict[str, float] = {}
    for r in rows:
        rid = canonicalize_resource_id(str(r.resource_id))
        if not rid:
            continue
        out[rid] = float(out.get(rid, 0.0)) + float(r.quantity or 0.0)
    return out


def _national_stock_map(db: Session, scenario_id: int | None) -> dict[str, float]:
    if scenario_id is None:
        return {}
    rows = db.query(
        ScenarioNationalStock.resource_id,
        func.coalesce(func.sum(ScenarioNationalStock.quantity), 0.0).label("quantity"),
    ).filter(
        ScenarioNationalStock.scenario_id == int(scenario_id)
    ).group_by(
        ScenarioNationalStock.resource_id
    ).all()
    out: dict[str, float] = {}
    for r in rows:
        rid = canonicalize_resource_id(str(r.resource_id))
        if not rid:
            continue
        out[rid] = float(out.get(rid, 0.0)) + float(r.quantity or 0.0)
    return out


def _district_stock_map(db: Session, district_code: str) -> dict[str, float]:
    latest_run_id = get_latest_solver_run_id(db)
    if latest_run_id is None:
        return {}
    rows = db.query(
        InventorySnapshot.resource_id,
        func.coalesce(func.sum(InventorySnapshot.quantity), 0.0).label("quantity"),
    ).filter(
        InventorySnapshot.solver_run_id == int(latest_run_id),
        InventorySnapshot.district_code == str(district_code),
    ).group_by(
        InventorySnapshot.resource_id
    ).all()
    out: dict[str, float] = {}
    for r in rows:
        rid = canonicalize_resource_id(str(r.resource_id))
        if not rid:
            continue
        out[rid] = float(out.get(rid, 0.0)) + float(r.quantity or 0.0)
    return out


def _norm_code(value: str | int | None) -> str:
    text = str(value or "").strip()
    return text.lstrip("0") or "0"


def _to_float(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


@lru_cache(maxsize=1)
def _load_district_stock_csv() -> dict[tuple[str, str], float]:
    path = Path(PHASE4_RESOURCE_DATA) / "district_resource_stock.csv"
    out: dict[tuple[str, str], float] = {}
    if not path.exists():
        return out
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            dcode = _norm_code(row.get("district_code"))
            rid = canonicalize_resource_id(str(row.get("resource_id") or "").strip())
            if not dcode or not rid:
                continue
            key = (dcode, rid)
            out[key] = out.get(key, 0.0) + _to_float(row.get("quantity"))
    return out


@lru_cache(maxsize=1)
def _load_state_stock_csv() -> dict[tuple[str, str], float]:
    path = Path(PHASE4_RESOURCE_DATA) / "state_resource_stock.csv"
    out: dict[tuple[str, str], float] = {}
    if not path.exists():
        return out
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            scode = _norm_code(row.get("state_code"))
            rid = canonicalize_resource_id(str(row.get("resource_id") or "").strip())
            if not scode or not rid:
                continue
            key = (scode, rid)
            out[key] = out.get(key, 0.0) + _to_float(row.get("quantity"))
    return out


@lru_cache(maxsize=1)
def _load_national_stock_csv() -> dict[str, float]:
    path = Path(PHASE4_RESOURCE_DATA) / "national_resource_stock.csv"
    out: dict[str, float] = {}
    if not path.exists():
        return out
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rid = canonicalize_resource_id(str(row.get("resource_id") or "").strip())
            if not rid:
                continue
            out[rid] = out.get(rid, 0.0) + _to_float(row.get("quantity"))
    return out


def _district_stock_csv_map(district_code: str) -> dict[str, float]:
    dcode = _norm_code(district_code)
    rows = _load_district_stock_csv()
    return {rid: qty for (code, rid), qty in rows.items() if code == dcode}


def _state_stock_csv_map(state_code: str) -> dict[str, float]:
    scode = _norm_code(state_code)
    rows = _load_state_stock_csv()
    return {rid: qty for (code, rid), qty in rows.items() if code == scode}


def _merge_with_csv_fallback(primary: dict[str, float], fallback: dict[str, float], resource_ids: list[str]) -> dict[str, float]:
    if len(primary) >= len(resource_ids):
        return primary
    out: dict[str, float] = {}
    for rid in resource_ids:
        if rid in primary:
            out[rid] = float(primary[rid])
        elif rid in fallback:
            out[rid] = float(fallback[rid])
    return out


def _in_transit_for_district_map(db: Session, run_id: int | None, district_code: str) -> dict[str, float]:
    if run_id is None:
        return {}
    rows = db.query(
        ShipmentPlan.resource_id,
        func.coalesce(func.sum(ShipmentPlan.quantity), 0.0).label("quantity"),
    ).filter(
        ShipmentPlan.solver_run_id == int(run_id),
        ShipmentPlan.to_district == str(district_code),
        func.lower(func.coalesce(ShipmentPlan.status, "planned")).in_(["planned", "in_transit"]),
    ).group_by(ShipmentPlan.resource_id).all()
    return {str(r.resource_id): float(r.quantity or 0.0) for r in rows}


def _in_transit_for_state_map(db: Session, run_id: int | None, state_code: str) -> dict[str, float]:
    if run_id is None:
        return {}
    district_rows = db.query(District.district_code).filter(District.state_code == str(state_code)).all()
    district_codes = [str(r[0]) for r in district_rows]
    if not district_codes:
        return {}
    rows = db.query(
        ShipmentPlan.resource_id,
        func.coalesce(func.sum(ShipmentPlan.quantity), 0.0).label("quantity"),
    ).filter(
        ShipmentPlan.solver_run_id == int(run_id),
        ShipmentPlan.to_district.in_(district_codes),
        func.lower(func.coalesce(ShipmentPlan.status, "planned")).in_(["planned", "in_transit"]),
    ).group_by(ShipmentPlan.resource_id).all()
    return {str(r.resource_id): float(r.quantity or 0.0) for r in rows}


def _in_transit_national_map(db: Session, run_id: int | None) -> dict[str, float]:
    if run_id is None:
        return {}
    rows = db.query(
        ShipmentPlan.resource_id,
        func.coalesce(func.sum(ShipmentPlan.quantity), 0.0).label("quantity"),
    ).filter(
        ShipmentPlan.solver_run_id == int(run_id),
        func.lower(func.coalesce(ShipmentPlan.status, "planned")).in_(["planned", "in_transit"]),
    ).group_by(ShipmentPlan.resource_id).all()
    return {str(r.resource_id): float(r.quantity or 0.0) for r in rows}


def _canonical_resource_ids(db: Session) -> list[str]:
    rows = db.query(Resource.resource_id).filter(Resource.resource_id.in_(CANONICAL_RESOURCE_ORDER)).all()
    existing = {str(r[0]) for r in rows}
    return [rid for rid in CANONICAL_RESOURCE_ORDER if rid in existing]


def _pool_stock_map(
    db: Session,
    state_code: str | None = None,
    include_all_states: bool = False,
) -> dict[str, float]:
    query = db.query(
        PoolTransaction.resource_id,
        func.coalesce(func.sum(PoolTransaction.quantity_delta), 0.0).label("quantity"),
    )
    if include_all_states:
        query = query.filter(PoolTransaction.state_code.isnot(None))
    elif state_code is None:
        query = query.filter(PoolTransaction.state_code == "NATIONAL")
    else:
        query = query.filter(PoolTransaction.state_code == str(state_code))

    rows = query.group_by(PoolTransaction.resource_id).all()
    out: dict[str, float] = {}
    for row in rows:
        rid = canonicalize_resource_id(str(row.resource_id))
        if not rid:
            continue
        qty = float(row.quantity or 0.0)
        if qty <= 1e-9:
            continue
        out[rid] = max(0.0, float(out.get(rid, 0.0)) + qty)
    return out


def get_district_stock_rows(db: Session, district_code: str):
    scenario_id = _latest_scenario_id(db)
    latest_run_id = get_latest_solver_run_id(db)
    district_state = db.query(District.state_code).filter(District.district_code == str(district_code)).first()
    state_code = None if district_state is None else str(district_state[0])

    resource_ids = _canonical_resource_ids(db)

    district_map = _merge_with_csv_fallback(
        _district_stock_map(db, district_code),
        _district_stock_csv_map(district_code),
        resource_ids,
    )
    state_map = _merge_with_csv_fallback(
        _state_stock_map(db, scenario_id, state_code=state_code),
        _state_stock_csv_map(state_code or ""),
        resource_ids,
    )
    national_map = _merge_with_csv_fallback(
        _national_stock_map(db, scenario_id),
        _load_national_stock_csv(),
        resource_ids,
    )
    district_adj_map, state_adj_map, national_adj_map = get_refill_adjustment_maps(db)
    state_pool_map = _pool_stock_map(db, state_code=state_code)
    national_pool_map = _pool_stock_map(db, state_code="NATIONAL")
    in_transit_map = _in_transit_for_district_map(db, latest_run_id, district_code)
    return [
        {
            "resource_id": rid,
            "district_stock": max(0.0, float(district_map.get(rid, 0.0)) + float(district_adj_map.get((str(district_code), rid), 0.0))),
            "state_stock": max(0.0, float(state_map.get(rid, 0.0)) + float(state_adj_map.get((str(state_code), rid), 0.0)) + float(state_pool_map.get(rid, 0.0))),
            "national_stock": max(0.0, float(national_map.get(rid, 0.0)) + float(national_adj_map.get(rid, 0.0)) + float(national_pool_map.get(rid, 0.0))),
            "in_transit": float(in_transit_map.get(rid, 0.0)),
            "available_stock": max(0.0, float(district_map.get(rid, 0.0)) + float(district_adj_map.get((str(district_code), rid), 0.0)))
            + max(0.0, float(state_map.get(rid, 0.0)) + float(state_adj_map.get((str(state_code), rid), 0.0)) + float(state_pool_map.get(rid, 0.0)))
            + max(0.0, float(national_map.get(rid, 0.0)) + float(national_adj_map.get(rid, 0.0)) + float(national_pool_map.get(rid, 0.0)))
            - float(in_transit_map.get(rid, 0.0)),
        }
        for rid in resource_ids
    ]


def get_state_stock_rows(db: Session, state_code: str):
    scenario_id = _latest_scenario_id(db)
    latest_run_id = get_latest_solver_run_id(db)
    resource_ids = _canonical_resource_ids(db)
    state_map = _merge_with_csv_fallback(
        _state_stock_map(db, scenario_id, state_code=state_code),
        _state_stock_csv_map(state_code),
        resource_ids,
    )
    national_map = _merge_with_csv_fallback(
        _national_stock_map(db, scenario_id),
        _load_national_stock_csv(),
        resource_ids,
    )
    _, state_adj_map, national_adj_map = get_refill_adjustment_maps(db)
    state_pool_map = _pool_stock_map(db, state_code=state_code)
    national_pool_map = _pool_stock_map(db, state_code="NATIONAL")
    in_transit_map = _in_transit_for_state_map(db, latest_run_id, state_code)
    return [
        {
            "resource_id": rid,
            "district_stock": 0.0,
            "state_stock": max(0.0, float(state_map.get(rid, 0.0)) + float(state_adj_map.get((str(state_code), rid), 0.0)) + float(state_pool_map.get(rid, 0.0))),
            "national_stock": max(0.0, float(national_map.get(rid, 0.0)) + float(national_adj_map.get(rid, 0.0)) + float(national_pool_map.get(rid, 0.0))),
            "in_transit": float(in_transit_map.get(rid, 0.0)),
            "available_stock": max(0.0, float(state_map.get(rid, 0.0)) + float(state_adj_map.get((str(state_code), rid), 0.0)) + float(state_pool_map.get(rid, 0.0)))
            + max(0.0, float(national_map.get(rid, 0.0)) + float(national_adj_map.get(rid, 0.0)) + float(national_pool_map.get(rid, 0.0)))
            - float(in_transit_map.get(rid, 0.0)),
        }
        for rid in resource_ids
    ]


def get_national_stock_rows(db: Session):
    scenario_id = _latest_scenario_id(db)
    latest_run_id = get_latest_solver_run_id(db)
    resource_ids = _canonical_resource_ids(db)
    national_map = _merge_with_csv_fallback(
        _national_stock_map(db, scenario_id),
        _load_national_stock_csv(),
        resource_ids,
    )
    global_pool_map = _pool_stock_map(db, state_code="NATIONAL")
    _, _, national_adj_map = get_refill_adjustment_maps(db)
    in_transit_map = _in_transit_national_map(db, latest_run_id)
    return [
        {
            "resource_id": rid,
            "district_stock": 0.0,
            "state_stock": 0.0,
            "national_stock": max(0.0, float(national_map.get(rid, 0.0)) + float(national_adj_map.get(rid, 0.0)) + float(global_pool_map.get(rid, 0.0))),
            "in_transit": float(in_transit_map.get(rid, 0.0)),
            "available_stock": max(0.0, float(national_map.get(rid, 0.0)) + float(national_adj_map.get(rid, 0.0)) + float(global_pool_map.get(rid, 0.0))) - float(in_transit_map.get(rid, 0.0)),
        }
        for rid in resource_ids
    ]
