from __future__ import annotations

import random
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.resource import Resource
from app.models.scenario import Scenario
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.scenario_request import ScenarioRequest
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.solver_run import SolverRun
from app.models.stock_refill_transaction import StockRefillTransaction
from app.config import PHASE4_RESOURCE_DATA


_PRESET_BANDS: dict[str, tuple[float, float]] = {
    "very_low": (0.40, 0.80),
    "low": (0.80, 1.00),
    "medium": (1.00, 1.35),
    "high": (1.35, 1.85),
    "extreme": (1.85, 2.80),
}


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(fallback)


def _get_scenario(db: Session, scenario_id: int) -> Scenario:
    row = db.query(Scenario).filter(Scenario.id == int(scenario_id)).first()
    if row is None:
        raise ValueError("Scenario not found")
    return row


def _load_stock_maps() -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float], dict[str, float]]:
    district_path = PHASE4_RESOURCE_DATA / "district_resource_stock.csv"
    state_path = PHASE4_RESOURCE_DATA / "state_resource_stock.csv"
    national_path = PHASE4_RESOURCE_DATA / "national_resource_stock.csv"

    district_df = pd.read_csv(district_path) if district_path.exists() else pd.DataFrame(columns=["district_code", "resource_id", "quantity"])
    state_df = pd.read_csv(state_path) if state_path.exists() else pd.DataFrame(columns=["state_code", "resource_id", "quantity"])
    national_df = pd.read_csv(national_path) if national_path.exists() else pd.DataFrame(columns=["resource_id", "quantity"])

    if not district_df.empty:
        district_df["district_code"] = district_df["district_code"].astype(str)
        district_df["resource_id"] = district_df["resource_id"].astype(str)
        district_df["quantity"] = district_df["quantity"].astype(float)
        district_map = {
            (str(r.district_code), str(r.resource_id)): float(r.quantity)
            for r in district_df.groupby(["district_code", "resource_id"], as_index=False)["quantity"].sum().itertuples(index=False)
        }
    else:
        district_map = {}

    if not state_df.empty:
        state_df["state_code"] = state_df["state_code"].astype(str)
        state_df["resource_id"] = state_df["resource_id"].astype(str)
        state_df["quantity"] = state_df["quantity"].astype(float)
        state_map = {
            (str(r.state_code), str(r.resource_id)): float(r.quantity)
            for r in state_df.groupby(["state_code", "resource_id"], as_index=False)["quantity"].sum().itertuples(index=False)
        }
    else:
        state_map = {}

    if not national_df.empty:
        national_df["resource_id"] = national_df["resource_id"].astype(str)
        national_df["quantity"] = national_df["quantity"].astype(float)
        national_map = {
            str(r.resource_id): float(r.quantity)
            for r in national_df.groupby(["resource_id"], as_index=False)["quantity"].sum().itertuples(index=False)
        }
    else:
        national_map = {}

    return district_map, state_map, national_map


def _latest_live_completed_run_id(db: Session) -> int | None:
    row = (
        db.query(SolverRun.id)
        .filter(
            SolverRun.mode == "live",
            SolverRun.status == "completed",
        )
        .order_by(SolverRun.id.desc())
        .first()
    )
    return None if row is None else int(row[0])


def finalize_scenario(db: Session, scenario_id: int) -> dict[str, Any]:
    scenario = _get_scenario(db, scenario_id)
    scenario.status = "finalized"
    db.commit()
    db.refresh(scenario)
    return {
        "scenario_id": int(scenario.id),
        "status": str(scenario.status),
        "finalized_at": datetime.utcnow().isoformat() + "Z",
    }


def clone_scenario_as_new(db: Session, scenario_id: int, name: str | None = None) -> dict[str, Any]:
    source = _get_scenario(db, scenario_id)
    clone_name = str(name or f"{source.name} (clone)").strip()
    if not clone_name:
        clone_name = f"Scenario {int(source.id)} clone"

    clone = Scenario(name=clone_name, status="created")
    db.add(clone)
    db.flush()

    source_requests = db.query(ScenarioRequest).filter(ScenarioRequest.scenario_id == int(source.id)).all()
    source_state_stock = db.query(ScenarioStateStock).filter(ScenarioStateStock.scenario_id == int(source.id)).all()
    source_national_stock = db.query(ScenarioNationalStock).filter(ScenarioNationalStock.scenario_id == int(source.id)).all()

    for row in source_requests:
        db.add(
            ScenarioRequest(
                scenario_id=int(clone.id),
                district_code=str(row.district_code),
                state_code=str(row.state_code),
                resource_id=str(row.resource_id),
                time=int(row.time),
                quantity=float(row.quantity),
            )
        )

    for row in source_state_stock:
        db.add(
            ScenarioStateStock(
                scenario_id=int(clone.id),
                state_code=str(row.state_code),
                resource_id=str(row.resource_id),
                quantity=float(row.quantity),
            )
        )

    for row in source_national_stock:
        db.add(
            ScenarioNationalStock(
                scenario_id=int(clone.id),
                resource_id=str(row.resource_id),
                quantity=float(row.quantity),
            )
        )

    db.commit()
    db.refresh(clone)
    return {
        "source_scenario_id": int(source.id),
        "cloned_scenario_id": int(clone.id),
        "name": str(clone.name),
        "copied": {
            "requests": len(source_requests),
            "state_stock": len(source_state_stock),
            "national_stock": len(source_national_stock),
        },
    }


def build_randomizer_preview(db: Session, scenario_id: int, config: dict[str, Any] | None = None) -> dict[str, Any]:
    _get_scenario(db, scenario_id)
    payload = dict(config or {})

    preset = str(payload.get("preset") or "medium").strip().lower()
    if preset not in _PRESET_BANDS:
        raise ValueError("Invalid preset. Use: very_low, low, medium, high, extreme")

    seed = payload.get("seed")
    rng = random.Random(None if seed in (None, "") else int(seed))

    horizon = max(1, min(30, _safe_int(payload.get("time_horizon"), 3)))
    stress_mode = bool(payload.get("stress_mode", False))
    replace_existing = bool(payload.get("replace_existing", True))
    stock_aware_distribution = bool(payload.get("stock_aware_distribution", False))
    quantity_mode = str(payload.get("quantity_mode") or ("stock_aware" if stock_aware_distribution else "fixed")).strip().lower()
    if quantity_mode not in {"fixed", "stock_aware"}:
        quantity_mode = "fixed"
    stock_ratio_min = max(0.01, min(0.9, _safe_float(payload.get("stock_ratio_min"), 0.05)))
    stock_ratio_max = max(stock_ratio_min, min(0.95, _safe_float(payload.get("stock_ratio_max"), 0.25)))

    selected_state_codes = [str(x) for x in (payload.get("state_codes") or []) if str(x).strip()]
    selected_district_codes = [str(x) for x in (payload.get("district_codes") or []) if str(x).strip()]
    selected_resource_ids = [str(x) for x in (payload.get("resource_ids") or []) if str(x).strip()]

    district_count = max(1, min(50, _safe_int(payload.get("district_count"), 6)))
    resource_count = max(1, min(25, _safe_int(payload.get("resource_count"), 5)))

    districts_query = db.query(District)
    if selected_state_codes:
        districts_query = districts_query.filter(District.state_code.in_(selected_state_codes))
    districts_all = districts_query.order_by(District.state_code.asc(), District.district_code.asc()).all()
    districts_map = {str(d.district_code): str(d.state_code or "") for d in districts_all}

    if selected_district_codes:
        district_codes = [d for d in selected_district_codes if d in districts_map]
    else:
        pool = [str(d.district_code) for d in districts_all]
        district_codes = rng.sample(pool, k=min(district_count, len(pool))) if pool else []

    resources_all = [str(r.resource_id) for r in db.query(Resource).order_by(Resource.resource_id.asc()).all()]
    if selected_resource_ids:
        resource_ids = [r for r in selected_resource_ids if r in set(resources_all)]
    else:
        resource_ids = rng.sample(resources_all, k=min(resource_count, len(resources_all))) if resources_all else []

    if not district_codes:
        raise ValueError("No districts available for randomization")
    if not resource_ids:
        raise ValueError("No resources available for randomization")

    latest_run_id = _latest_live_completed_run_id(db)

    baseline_slot_map: dict[tuple[str, str, int], float] = {}
    baseline_by_resource: dict[str, float] = {}
    if latest_run_id is not None:
        baseline_rows = (
            db.query(
                FinalDemand.district_code,
                FinalDemand.resource_id,
                FinalDemand.time,
                func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0).label("qty"),
            )
            .filter(FinalDemand.solver_run_id == int(latest_run_id))
            .group_by(FinalDemand.district_code, FinalDemand.resource_id, FinalDemand.time)
            .all()
        )
        for row in baseline_rows:
            key = (str(row.district_code), str(row.resource_id), int(row.time))
            qty = float(row.qty or 0.0)
            baseline_slot_map[key] = qty
            baseline_by_resource[str(row.resource_id)] = baseline_by_resource.get(str(row.resource_id), 0.0) + qty

    low_mul, high_mul = _PRESET_BANDS[preset]
    fallback_base = {
        "very_low": 25.0,
        "low": 60.0,
        "medium": 120.0,
        "high": 220.0,
        "extreme": 360.0,
    }[preset]

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    district_stock_map: dict[tuple[str, str], float] = {}
    state_stock_map: dict[tuple[str, str], float] = {}
    national_stock_map: dict[str, float] = {}
    if quantity_mode == "stock_aware":
        district_stock_map, state_stock_map, national_stock_map = _load_stock_maps()

    for district_code in district_codes:
        state_code = districts_map.get(str(district_code), "")
        for resource_id in resource_ids:
            resource_baseline = baseline_by_resource.get(str(resource_id), fallback_base)
            pair_available_stock = float(
                district_stock_map.get((str(district_code), str(resource_id)), 0.0)
                + state_stock_map.get((str(state_code), str(resource_id)), 0.0)
                + national_stock_map.get(str(resource_id), 0.0)
            )
            pair_budget = float(rng.uniform(stock_ratio_min, stock_ratio_max) * max(0.0, pair_available_stock)) if quantity_mode == "stock_aware" else 0.0
            per_slot_stock_target = float(pair_budget / max(1, horizon)) if quantity_mode == "stock_aware" else 0.0
            remaining_stock_budget = float(max(0.0, pair_budget))
            for t in range(1, horizon + 1):
                slot_baseline = baseline_slot_map.get((str(district_code), str(resource_id), int(t)), 0.0)
                baseline_qty = float(slot_baseline if slot_baseline > 0.0 else max(10.0, resource_baseline / max(1.0, float(horizon) * max(1.0, float(len(district_codes))))))

                multiplier = rng.uniform(low_mul, high_mul)
                noise = rng.uniform(0.85, 1.15)
                if quantity_mode == "stock_aware":
                    generated = float(max(0.0, per_slot_stock_target * noise))
                    quantity = float(max(0.0, min(generated, remaining_stock_budget)))
                    quantity = float(round(quantity, 2))
                    remaining_stock_budget = float(max(0.0, remaining_stock_budget - quantity))
                    if pair_available_stock <= 0.0:
                        warnings.append(
                            f"stock_aware_zero_supply:{district_code}:{resource_id}:state={state_code or 'unknown'}"
                        )
                else:
                    quantity = float(max(1.0, round(baseline_qty * multiplier * noise, 2)))

                if quantity_mode != "stock_aware" and not stress_mode:
                    hard_cap = float(max(15.0, baseline_qty * 2.5))
                    if quantity > hard_cap:
                        warnings.append(
                            f"clamped:{district_code}:{resource_id}:t{t}:generated={quantity:.2f}:cap={hard_cap:.2f}"
                        )
                        quantity = float(round(hard_cap, 2))

                rows.append(
                    {
                        "district_code": str(district_code),
                        "state_code": str(state_code),
                        "resource_id": str(resource_id),
                        "time": int(t),
                        "quantity": float(quantity),
                        "baseline_quantity": float(round(baseline_qty, 2)),
                        "surge_multiplier": float(round(multiplier, 4)),
                        "available_stock": float(round(pair_available_stock, 2)),
                    }
                )

    total_qty = float(sum(float(r["quantity"]) for r in rows))
    baseline_total = float(sum(float(r["baseline_quantity"]) for r in rows))
    demand_ratio = (total_qty / baseline_total) if baseline_total > 1e-9 else None

    return {
        "scenario_id": int(scenario_id),
        "preset": preset,
        "seed": (None if seed in (None, "") else int(seed)),
        "time_horizon": int(horizon),
        "stress_mode": bool(stress_mode),
        "quantity_mode": quantity_mode,
        "stock_aware_distribution": bool(quantity_mode == "stock_aware"),
        "stock_ratio_min": float(stock_ratio_min),
        "stock_ratio_max": float(stock_ratio_max),
        "replace_existing": bool(replace_existing),
        "latest_live_run_id": latest_run_id,
        "district_count": len(district_codes),
        "resource_count": len(resource_ids),
        "row_count": len(rows),
        "total_quantity": float(round(total_qty, 2)),
        "baseline_total_quantity": float(round(baseline_total, 2)),
        "demand_ratio_vs_baseline": (None if demand_ratio is None else float(round(demand_ratio, 4))),
        "guardrail_warnings": warnings[:200],
        "rows": rows,
    }


def apply_randomizer_to_scenario(db: Session, scenario_id: int, config: dict[str, Any] | None = None) -> dict[str, Any]:
    preview = build_randomizer_preview(db, scenario_id, config)
    replace_existing = bool(preview.get("replace_existing", True))
    rows = list(preview.get("rows") or [])

    if replace_existing:
        db.query(ScenarioRequest).filter(ScenarioRequest.scenario_id == int(scenario_id)).delete(synchronize_session=False)

    existing_map: dict[tuple[str, str, int], ScenarioRequest] = {}
    if not replace_existing:
        existing_rows = (
            db.query(ScenarioRequest)
            .filter(ScenarioRequest.scenario_id == int(scenario_id))
            .all()
        )
        for existing in existing_rows:
            key = (str(existing.district_code), str(existing.resource_id), int(existing.time))
            existing_map[key] = existing

    for row in rows:
        district_code = str(row["district_code"])
        state_code = str(row["state_code"])
        resource_id = str(row["resource_id"])
        time = int(row["time"])
        quantity = float(row["quantity"])

        if not replace_existing:
            key = (district_code, resource_id, time)
            existing = existing_map.get(key)
            if existing is not None:
                existing.quantity = float(existing.quantity or 0.0) + quantity
                if not existing.state_code:
                    existing.state_code = state_code
                continue

        db.add(
            ScenarioRequest(
                scenario_id=int(scenario_id),
                district_code=district_code,
                state_code=state_code,
                resource_id=resource_id,
                time=time,
                quantity=quantity,
            )
        )

    db.commit()
    return {
        "scenario_id": int(scenario_id),
        "applied_rows": len(rows),
        "replace_existing": bool(replace_existing),
        "total_quantity": float(preview.get("total_quantity") or 0.0),
        "demand_ratio_vs_baseline": preview.get("demand_ratio_vs_baseline"),
        "guardrail_warnings": preview.get("guardrail_warnings") or [],
    }


def revert_scenario_effects(db: Session, scenario_id: int, run_id: int | None = None) -> dict[str, Any]:
    _get_scenario(db, scenario_id)

    run_query = db.query(SolverRun.id).filter(SolverRun.scenario_id == int(scenario_id))
    if run_id is not None:
        run_query = run_query.filter(SolverRun.id == int(run_id))
    run_ids = [int(r[0]) for r in run_query.order_by(SolverRun.id.asc()).all()]

    if not run_ids:
        return {
            "scenario_id": int(scenario_id),
            "run_ids": [],
            "debit_rows": 0,
            "revert_rows_created": 0,
            "already_reverted": 0,
            "quantity_reverted": 0.0,
            "ok": True,
        }

    debits = (
        db.query(StockRefillTransaction)
        .filter(
            StockRefillTransaction.source == "solver_allocation_debit",
            StockRefillTransaction.solver_run_id.in_(run_ids),
        )
        .order_by(StockRefillTransaction.id.asc())
        .all()
    )

    created = 0
    already = 0
    qty_reverted = 0.0

    for debit in debits:
        marker = f"scenario_revert_credit_of:{int(debit.id)}"
        exists = (
            db.query(StockRefillTransaction.id)
            .filter(
                StockRefillTransaction.source == "scenario_revert_credit",
                StockRefillTransaction.reason == marker,
            )
            .first()
            is not None
        )
        if exists:
            already += 1
            continue

        reversal = StockRefillTransaction(
            scope=str(debit.scope),
            district_code=(None if debit.district_code is None else str(debit.district_code)),
            state_code=(None if debit.state_code is None else str(debit.state_code)),
            resource_id=str(debit.resource_id),
            quantity_delta=float(-float(debit.quantity_delta or 0.0)),
            reason=marker,
            actor_role="admin",
            actor_id="scenario_revert",
            source="scenario_revert_credit",
            solver_run_id=int(debit.solver_run_id) if debit.solver_run_id is not None else None,
        )
        db.add(reversal)
        created += 1
        qty_reverted += float(reversal.quantity_delta or 0.0)

    db.commit()

    return {
        "scenario_id": int(scenario_id),
        "run_ids": run_ids,
        "debit_rows": len(debits),
        "revert_rows_created": int(created),
        "already_reverted": int(already),
        "quantity_reverted": float(round(qty_reverted, 4)),
        "ok": True,
    }


def verify_scenario_revert_balance(db: Session, scenario_id: int, run_id: int | None = None) -> dict[str, Any]:
    _get_scenario(db, scenario_id)

    run_query = db.query(SolverRun.id).filter(SolverRun.scenario_id == int(scenario_id))
    if run_id is not None:
        run_query = run_query.filter(SolverRun.id == int(run_id))
    run_ids = [int(r[0]) for r in run_query.order_by(SolverRun.id.asc()).all()]

    if not run_ids:
        return {
            "scenario_id": int(scenario_id),
            "run_ids": [],
            "debit_total": 0.0,
            "revert_total": 0.0,
            "net_total": 0.0,
            "ok": True,
        }

    debit_total = float(
        db.query(func.coalesce(func.sum(StockRefillTransaction.quantity_delta), 0.0))
        .filter(
            StockRefillTransaction.source == "solver_allocation_debit",
            StockRefillTransaction.solver_run_id.in_(run_ids),
        )
        .scalar()
        or 0.0
    )

    revert_total = float(
        db.query(func.coalesce(func.sum(StockRefillTransaction.quantity_delta), 0.0))
        .filter(
            StockRefillTransaction.source == "scenario_revert_credit",
            StockRefillTransaction.solver_run_id.in_(run_ids),
        )
        .scalar()
        or 0.0
    )

    net_total = float(debit_total + revert_total)
    return {
        "scenario_id": int(scenario_id),
        "run_ids": run_ids,
        "debit_total": float(round(debit_total, 4)),
        "revert_total": float(round(revert_total, 4)),
        "net_total": float(round(net_total, 4)),
        "ok": abs(net_total) <= 1e-6,
    }
