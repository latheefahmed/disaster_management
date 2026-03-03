from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import CORE_ENGINE_ROOT, PHASE4_RESOURCE_DATA
from app.models.stock_refill_transaction import StockRefillTransaction
from app.models.solver_run import SolverRun
from app.services.canonical_resources import CANONICAL_RESOURCE_ORDER
from app.services.canonical_resources import canonicalize_resource_id
from app.services.resource_dictionary_service import resolve_resource_id


def _normalize_scope(scope: str) -> str:
    normalized = str(scope or "").strip().lower()
    if normalized not in {"district", "state", "national"}:
        raise ValueError("Invalid refill scope")
    return normalized


def _normalize_quantity(quantity: float) -> float:
    value = float(quantity)
    if value <= 0:
        raise ValueError("quantity must be greater than 0")
    return value


def create_stock_refill(
    db: Session,
    scope: str,
    resource_id: str,
    quantity: float,
    actor_role: str,
    actor_id: str,
    district_code: str | None = None,
    state_code: str | None = None,
    note: str | None = None,
):
    normalized_scope = _normalize_scope(scope)
    normalized_resource = resolve_resource_id(db, resource_id, strict=True)
    normalized_quantity = _normalize_quantity(quantity)

    if normalized_scope == "district" and not district_code:
        raise ValueError("district_code is required for district refill")
    if normalized_scope == "state" and not state_code:
        raise ValueError("state_code is required for state refill")

    row = StockRefillTransaction(
        scope=normalized_scope,
        district_code=(None if district_code is None else str(district_code)),
        state_code=(None if state_code is None else str(state_code)),
        resource_id=str(normalized_resource),
        quantity_delta=float(normalized_quantity),
        reason=f"manual_refill:{(note or '').strip()}".strip(":"),
        actor_role=str(actor_role),
        actor_id=str(actor_id),
        source="manual_refill",
        solver_run_id=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def record_solver_allocation_debits(db: Session, solver_run_id: int, allocation_rows: list[dict]):
    db.query(StockRefillTransaction).filter(
        StockRefillTransaction.source == "solver_allocation_debit",
        StockRefillTransaction.solver_run_id == int(solver_run_id),
    ).delete(synchronize_session=False)

    district_group: dict[tuple[str, str, str], float] = defaultdict(float)
    state_group: dict[tuple[str, str], float] = defaultdict(float)
    national_group: dict[str, float] = defaultdict(float)

    for row in allocation_rows:
        if bool(row.get("is_unmet")):
            continue
        qty = float(row.get("allocated_quantity") or 0.0)
        if qty <= 0:
            continue
        scope = str(row.get("supply_level") or "district").lower()
        resource_id = str(row.get("resource_id"))

        if scope == "district":
            district_group[(str(row.get("district_code")), str(row.get("state_code")), resource_id)] += qty
        elif scope == "state":
            state_code = str(row.get("origin_state_code") or row.get("state_code"))
            state_group[(state_code, resource_id)] += qty
        elif scope == "national":
            national_group[resource_id] += qty

    objects: list[StockRefillTransaction] = []
    for (district_code, state_code, resource_id), qty in district_group.items():
        objects.append(
            StockRefillTransaction(
                scope="district",
                district_code=district_code,
                state_code=state_code,
                resource_id=resource_id,
                quantity_delta=-float(qty),
                reason="solver_allocation_debit",
                actor_role="system",
                actor_id="solver",
                source="solver_allocation_debit",
                solver_run_id=int(solver_run_id),
            )
        )

    for (state_code, resource_id), qty in state_group.items():
        if state_code.upper() == "NATIONAL":
            continue
        objects.append(
            StockRefillTransaction(
                scope="state",
                district_code=None,
                state_code=state_code,
                resource_id=resource_id,
                quantity_delta=-float(qty),
                reason="solver_allocation_debit",
                actor_role="system",
                actor_id="solver",
                source="solver_allocation_debit",
                solver_run_id=int(solver_run_id),
            )
        )

    for resource_id, qty in national_group.items():
        objects.append(
            StockRefillTransaction(
                scope="national",
                district_code=None,
                state_code=None,
                resource_id=resource_id,
                quantity_delta=-float(qty),
                reason="solver_allocation_debit",
                actor_role="system",
                actor_id="solver",
                source="solver_allocation_debit",
                solver_run_id=int(solver_run_id),
            )
        )

    if objects:
        db.bulk_save_objects(objects)


def get_refill_adjustment_maps(db: Session):
    scenario_run_ids = {
        int(r[0])
        for r in db.query(SolverRun.id)
        .filter(SolverRun.mode == "scenario")
        .all()
    }

    def _exclude_scenario_solver_debits(query):
        if not scenario_run_ids:
            return query
        return query.filter(
            ~(
                (StockRefillTransaction.source == "solver_allocation_debit")
                & (StockRefillTransaction.solver_run_id.in_(scenario_run_ids))
            )
        )

    district_rows = db.query(
        StockRefillTransaction.district_code,
        StockRefillTransaction.resource_id,
        func.coalesce(func.sum(StockRefillTransaction.quantity_delta), 0.0).label("qty"),
    )
    district_rows = _exclude_scenario_solver_debits(district_rows).filter(
        StockRefillTransaction.scope == "district"
    ).group_by(
        StockRefillTransaction.district_code,
        StockRefillTransaction.resource_id,
    ).all()

    state_rows = db.query(
        StockRefillTransaction.state_code,
        StockRefillTransaction.resource_id,
        func.coalesce(func.sum(StockRefillTransaction.quantity_delta), 0.0).label("qty"),
    )
    state_rows = _exclude_scenario_solver_debits(state_rows).filter(
        StockRefillTransaction.scope == "state"
    ).group_by(
        StockRefillTransaction.state_code,
        StockRefillTransaction.resource_id,
    ).all()

    national_rows = db.query(
        StockRefillTransaction.resource_id,
        func.coalesce(func.sum(StockRefillTransaction.quantity_delta), 0.0).label("qty"),
    )
    national_rows = _exclude_scenario_solver_debits(national_rows).filter(
        StockRefillTransaction.scope == "national"
    ).group_by(
        StockRefillTransaction.resource_id,
    ).all()

    district_map: dict[tuple[str, str], float] = defaultdict(float)
    for r in district_rows:
        if not r.district_code:
            continue
        rid = canonicalize_resource_id(str(r.resource_id))
        if not rid:
            continue
        district_map[(str(r.district_code), str(rid))] += float(r.qty or 0.0)

    state_map: dict[tuple[str, str], float] = defaultdict(float)
    for r in state_rows:
        if not r.state_code:
            continue
        rid = canonicalize_resource_id(str(r.resource_id))
        if not rid:
            continue
        state_map[(str(r.state_code), str(rid))] += float(r.qty or 0.0)

    national_map: dict[str, float] = defaultdict(float)
    for r in national_rows:
        rid = canonicalize_resource_id(str(r.resource_id))
        if not rid:
            continue
        national_map[str(rid)] += float(r.qty or 0.0)

    return district_map, state_map, national_map


def _read_stock_csv(path: Path, key_columns: tuple[str, ...]) -> dict[tuple[str, ...], float]:
    out: dict[tuple[str, ...], float] = defaultdict(float)
    if not path.exists():
        return dict(out)
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = tuple(str(row.get(k) or "").strip() for k in key_columns)
            rid = str(row.get("resource_id") or "").strip()
            if not rid:
                continue
            qty = float(row.get("quantity") or 0.0)
            out[(*key, rid)] += qty
    return dict(out)


def _write_stock_csv(path: Path, rows: list[dict], columns: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _max0(value: float) -> float:
    return max(0.0, float(value or 0.0))


def build_live_stock_override_files(
    db: Session,
    district_base_path: str | None = None,
    state_base_path: str | None = None,
    national_base_path: str | None = None,
):
    district_map, state_map, national_map = get_refill_adjustment_maps(db)

    has_adjustments = bool(district_map) or bool(state_map) or bool(national_map)
    if not has_adjustments and not district_base_path and not state_base_path and not national_base_path:
        return None, None, None

    district_base = Path(district_base_path) if district_base_path else (Path(PHASE4_RESOURCE_DATA) / "district_resource_stock.csv")
    state_base = Path(state_base_path) if state_base_path else (Path(PHASE4_RESOURCE_DATA) / "state_resource_stock.csv")
    national_base = Path(national_base_path) if national_base_path else (Path(PHASE4_RESOURCE_DATA) / "national_resource_stock.csv")

    district_raw = _read_stock_csv(district_base, ("district_code",))
    state_raw = _read_stock_csv(state_base, ("state_code",))
    national_raw = _read_stock_csv(national_base, tuple())

    district_rows = []
    for (district_code, resource_id), qty in sorted(((k[0], k[1]), v) for k, v in district_raw.items()):
        adjusted = _max0(float(qty) + float(district_map.get((district_code, resource_id), 0.0)))
        district_rows.append({"district_code": district_code, "resource_id": resource_id, "quantity": adjusted})

    state_rows = []
    for (state_code, resource_id), qty in sorted(((k[0], k[1]), v) for k, v in state_raw.items()):
        adjusted = _max0(float(qty) + float(state_map.get((state_code, resource_id), 0.0)))
        state_rows.append({"state_code": state_code, "resource_id": resource_id, "quantity": adjusted})

    national_rows = []
    for (_, resource_id), qty in sorted(((k[:-1], k[-1]), v) for k, v in national_raw.items()):
        adjusted = _max0(float(qty) + float(national_map.get(resource_id, 0.0)))
        national_rows.append({"resource_id": resource_id, "quantity": adjusted})

    # Ensure canonical resources exist for every entity row in base data.
    canonical = set(CANONICAL_RESOURCE_ORDER)
    district_by_entity: dict[str, dict[str, float]] = defaultdict(dict)
    for row in district_rows:
        district_by_entity[str(row["district_code"])][str(row["resource_id"])] = float(row["quantity"])
    district_rows_full = []
    for district_code, rid_map in district_by_entity.items():
        for rid in CANONICAL_RESOURCE_ORDER:
            if rid in canonical:
                district_rows_full.append({"district_code": district_code, "resource_id": rid, "quantity": _max0(rid_map.get(rid, 0.0))})

    state_by_entity: dict[str, dict[str, float]] = defaultdict(dict)
    for row in state_rows:
        state_by_entity[str(row["state_code"])][str(row["resource_id"])] = float(row["quantity"])
    state_rows_full = []
    for state_code, rid_map in state_by_entity.items():
        for rid in CANONICAL_RESOURCE_ORDER:
            if rid in canonical:
                state_rows_full.append({"state_code": state_code, "resource_id": rid, "quantity": _max0(rid_map.get(rid, 0.0))})

    national_map_rows = {str(r["resource_id"]): float(r["quantity"]) for r in national_rows}
    national_rows_full = [{"resource_id": rid, "quantity": _max0(national_map_rows.get(rid, 0.0))} for rid in CANONICAL_RESOURCE_ORDER]

    out_root = Path(CORE_ENGINE_ROOT) / "phase4" / "scenarios" / "generated"
    district_out = out_root / "live_district_stock_with_refills.csv"
    state_out = out_root / "live_state_stock_with_refills.csv"
    national_out = out_root / "live_national_stock_with_refills.csv"

    _write_stock_csv(district_out, district_rows_full, ["district_code", "resource_id", "quantity"])
    _write_stock_csv(state_out, state_rows_full, ["state_code", "resource_id", "quantity"])
    _write_stock_csv(national_out, national_rows_full, ["resource_id", "quantity"])

    return str(district_out), str(state_out), str(national_out)
