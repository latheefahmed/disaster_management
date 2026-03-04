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


_INTENSITY_RATIOS: dict[str, float] = {
    "extremely_low": 0.20,
    "low": 0.40,
    "medium_low": 0.70,
    "medium": 1.00,
    "medium_high": 1.25,
    "high": 1.50,
    "extremely_high": 1.79,
}

_PRESET_ALIASES: dict[str, str] = {
    "very_low": "extremely_low",
    "extreme": "extremely_high",
}

_PRESET_PRIORITY_BANDS: dict[str, tuple[int, int]] = {
    "extremely_low": (1, 2),
    "low": (1, 3),
    "medium_low": (2, 3),
    "medium": (2, 4),
    "medium_high": (3, 4),
    "high": (3, 5),
    "extremely_high": (4, 5),
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


def _normalize_preset(raw: Any) -> str:
    value = str(raw or "medium").strip().lower()
    if value in _PRESET_ALIASES:
        return _PRESET_ALIASES[value]
    return value


def _distribute_total(total: float, weights: list[float]) -> list[float]:
    if total <= 0.0 or not weights:
        return [0.0 for _ in weights]
    clean = [max(0.000001, float(w)) for w in weights]
    weight_sum = float(sum(clean))
    raw = [float(total) * (w / weight_sum) for w in clean]
    rounded = [float(round(v, 2)) for v in raw]
    drift = float(round(float(total) - float(sum(rounded)), 2))
    if rounded:
        rounded[-1] = float(round(rounded[-1] + drift, 2))
        if rounded[-1] < 0.0:
            deficit = float(abs(rounded[-1]))
            rounded[-1] = 0.0
            for idx in range(len(rounded) - 2, -1, -1):
                give = min(rounded[idx], deficit)
                rounded[idx] = float(round(rounded[idx] - give, 2))
                deficit = float(round(deficit - give, 2))
                if deficit <= 1e-9:
                    break
    return rounded


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

    preset = _normalize_preset(payload.get("preset") or "medium")
    if preset not in _INTENSITY_RATIOS:
        raise ValueError("Invalid preset. Use: extremely_low, low, medium_low, medium, medium_high, high, extremely_high")

    seed = payload.get("seed")
    rng = random.Random(None if seed in (None, "") else int(seed))

    horizon = max(1, min(30, _safe_int(payload.get("time_horizon"), 3)))
    stress_mode = bool(payload.get("stress_mode", False))
    replace_existing = bool(payload.get("replace_existing", True))
    stock_aware_distribution = bool(payload.get("stock_aware_distribution", True))
    quantity_mode = str(payload.get("quantity_mode") or ("stock_aware" if stock_aware_distribution else "fixed")).strip().lower()
    if quantity_mode not in {"fixed", "stock_aware"}:
        quantity_mode = "stock_aware"

    selected_state_codes = list(dict.fromkeys([str(x) for x in (payload.get("state_codes") or []) if str(x).strip()]))
    selected_district_codes = list(dict.fromkeys([str(x) for x in (payload.get("district_codes") or []) if str(x).strip()]))
    selected_resource_ids = list(dict.fromkeys([str(x) for x in (payload.get("resource_ids") or []) if str(x).strip()]))

    if not selected_district_codes:
        raise ValueError("Randomizer requires explicit district selection from Hierarchical Selector")
    if not selected_resource_ids:
        raise ValueError("Randomizer requires explicit resource selection from Hierarchical Selector")

    districts_query = db.query(District)
    if selected_state_codes:
        districts_query = districts_query.filter(District.state_code.in_(selected_state_codes))
    districts_all = districts_query.order_by(District.state_code.asc(), District.district_code.asc()).all()
    districts_map = {str(d.district_code): str(d.state_code or "") for d in districts_all}

    district_codes = [d for d in selected_district_codes if d in districts_map]

    resources_all = [str(r.resource_id) for r in db.query(Resource).order_by(Resource.resource_id.asc()).all()]
    resources_set = set(resources_all)
    resource_ids = [r for r in selected_resource_ids if r in resources_set]

    if not district_codes:
        raise ValueError("No valid districts found in selected state scope")
    if not resource_ids:
        raise ValueError("No valid resources found in selection")

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    stock_backed_rows = 0
    zero_stock_rows = 0
    available_stock_total = 0.0
    priority_total = 0
    time_index_total = 0.0
    district_stock_map, state_stock_map, national_stock_map = _load_stock_maps()

    state_override_rows = (
        db.query(ScenarioStateStock)
        .filter(ScenarioStateStock.scenario_id == int(scenario_id))
        .all()
    )
    state_override_map: dict[tuple[str, str], float] = {}
    for row in state_override_rows:
        key = (str(row.state_code), str(row.resource_id))
        state_override_map[key] = state_override_map.get(key, 0.0) + float(row.quantity or 0.0)

    national_override_rows = (
        db.query(ScenarioNationalStock)
        .filter(ScenarioNationalStock.scenario_id == int(scenario_id))
        .all()
    )
    national_override_map: dict[str, float] = {}
    for row in national_override_rows:
        key = str(row.resource_id)
        national_override_map[key] = national_override_map.get(key, 0.0) + float(row.quantity or 0.0)

    state_district_count: dict[str, int] = {}
    for district_code in district_codes:
        state_code = str(districts_map.get(str(district_code), ""))
        state_district_count[state_code] = state_district_count.get(state_code, 0) + 1

    total_selected_districts = max(1, len(district_codes))

    pair_contexts: list[dict[str, Any]] = []
    for district_code in district_codes:
        state_code = districts_map.get(str(district_code), "")
        state_divisor = max(1, int(state_district_count.get(str(state_code), 1)))
        for resource_id in resource_ids:
            district_stock = float(district_stock_map.get((str(district_code), str(resource_id)), 0.0))

            state_total = float(state_override_map.get((str(state_code), str(resource_id)), state_stock_map.get((str(state_code), str(resource_id)), 0.0)))
            national_total = float(national_override_map.get(str(resource_id), national_stock_map.get(str(resource_id), 0.0)))

            state_share = float(state_total / float(state_divisor))
            national_share = float(national_total / float(total_selected_districts))
            pair_supply = float(max(0.0, district_stock + state_share + national_share))

            pair_contexts.append(
                {
                    "district_code": str(district_code),
                    "state_code": str(state_code),
                    "resource_id": str(resource_id),
                    "district_stock": district_stock,
                    "state_stock": state_share,
                    "national_stock": national_share,
                    "pair_supply": pair_supply,
                }
            )

    total_available_supply = float(sum(float(x["pair_supply"]) for x in pair_contexts))
    ratio = float(_INTENSITY_RATIOS[preset])
    target_total_demand = float(round(total_available_supply * ratio, 2))

    if total_available_supply <= 1e-9:
        warnings.append("no_supply_detected_in_selected_scope")

    pair_weights: list[float] = []
    for ctx in pair_contexts:
        base_weight = float(max(1e-6, float(ctx["pair_supply"])))
        jitter = float(rng.uniform(0.85, 1.15))
        pair_weights.append(base_weight * jitter)
    pair_targets = _distribute_total(target_total_demand, pair_weights)

    for idx, ctx in enumerate(pair_contexts):
        district_code = str(ctx["district_code"])
        state_code = str(ctx["state_code"])
        resource_id = str(ctx["resource_id"])
        pair_supply = float(ctx["pair_supply"])
        pair_target = float(pair_targets[idx] if idx < len(pair_targets) else 0.0)

        slot_weights: list[float] = []
        for t in range(1, horizon + 1):
            base = float(rng.uniform(0.75, 1.35))
            if stress_mode and t <= max(1, horizon // 2):
                base *= 1.15
            slot_weights.append(base)
        slot_quantities = _distribute_total(pair_target, slot_weights)

        for t in range(1, horizon + 1):
            quantity = float(slot_quantities[t - 1])
            available_stock_total += float(max(0.0, pair_supply))
            if pair_supply > 0.0:
                stock_backed_rows += 1
            else:
                zero_stock_rows += 1

            p_low, p_high = _PRESET_PRIORITY_BANDS.get(preset, (2, 4))
            priority = int(rng.randint(int(p_low), int(p_high)))
            if stress_mode and t <= max(1, horizon // 2):
                priority = int(min(5, priority + 1))
            urgency = int(min(5, max(1, priority + (1 if stress_mode else 0))))
            time_index = float(round(float((horizon - t + 1) / max(1, horizon)), 4))
            priority_total += int(priority)
            time_index_total += float(time_index)

            rows.append(
                {
                    "district_code": district_code,
                    "state_code": state_code,
                    "resource_id": resource_id,
                    "time": int(t),
                    "quantity": float(quantity),
                    "baseline_quantity": float(round(pair_supply / max(1, horizon), 2)),
                    "surge_multiplier": float(round(ratio, 4)),
                    "available_stock": float(round(pair_supply, 2)),
                    "district_stock": float(round(float(ctx["district_stock"]), 2)),
                    "state_stock": float(round(float(ctx["state_stock"]), 2)),
                    "national_stock": float(round(float(ctx["national_stock"]), 2)),
                    "priority": int(priority),
                    "urgency": int(urgency),
                    "time_index": float(time_index),
                }
            )

    if quantity_mode == "stock_aware" and stock_backed_rows == 0 and rows:
        warnings.append("stock_aware_no_stock_backing_detected")

    total_qty = float(sum(float(r["quantity"]) for r in rows))
    baseline_total = float(round(total_available_supply, 2))
    demand_ratio = (total_qty / total_available_supply) if total_available_supply > 1e-9 else None
    expected_shortage_estimate = float(max(0.0, total_qty - total_available_supply))

    return {
        "scenario_id": int(scenario_id),
        "preset": preset,
        "intensity_ratio": float(ratio),
        "seed": (None if seed in (None, "") else int(seed)),
        "time_horizon": int(horizon),
        "stress_mode": bool(stress_mode),
        "quantity_mode": quantity_mode,
        "stock_aware_distribution": bool(quantity_mode == "stock_aware"),
        "replace_existing": bool(replace_existing),
        "latest_live_run_id": _latest_live_completed_run_id(db),
        "district_count": len(district_codes),
        "resource_count": len(resource_ids),
        "selected_districts": district_codes,
        "selected_resources": resource_ids,
        "row_count": len(rows),
        "total_quantity": float(round(total_qty, 2)),
        "baseline_total_quantity": float(round(baseline_total, 2)),
        "demand_ratio_vs_baseline": (None if demand_ratio is None else float(round(demand_ratio, 4))),
        "total_available_supply": float(round(total_available_supply, 2)),
        "total_generated_demand": float(round(total_qty, 2)),
        "demand_supply_ratio": (None if demand_ratio is None else float(round(demand_ratio, 4))),
        "expected_shortage_estimate": float(round(expected_shortage_estimate, 2)),
        "avg_available_stock": (0.0 if not rows else float(round(available_stock_total / len(rows), 4))),
        "avg_priority": (0.0 if not rows else float(round(priority_total / len(rows), 4))),
        "avg_time_index": (0.0 if not rows else float(round(time_index_total / len(rows), 4))),
        "stock_backed_rows": int(stock_backed_rows),
        "zero_stock_rows": int(zero_stock_rows),
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
