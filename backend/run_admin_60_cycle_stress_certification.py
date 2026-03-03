from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func

from app.config import PHASE4_RESOURCE_DATA
from app.database import SessionLocal
from app.main import app
from app.models.allocation import Allocation
from app.models.mutual_aid_offer import MutualAidOffer
from app.models.mutual_aid_request import MutualAidRequest
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.solver_run import SolverRun
from app.services.mutual_aid_service import (
    create_mutual_aid_offer,
    create_requests_from_unmet_allocations,
    get_candidate_states,
    respond_to_offer,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(resp) -> dict[str, Any]:
    try:
        payload = resp.json()
        return payload if isinstance(payload, dict) else {"payload": payload}
    except Exception:
        return {"raw": getattr(resp, "text", "")}


def _report_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parent
    return (
        root / "ADMIN_60_STRESS_CERT_REPORT.json",
        root / "ADMIN_60_STRESS_CERT_REPORT.md",
    )


def _load_scope_stock_totals() -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    district_file = Path(PHASE4_RESOURCE_DATA) / "district_resource_stock.csv"
    state_file = Path(PHASE4_RESOURCE_DATA) / "state_resource_stock.csv"
    national_file = Path(PHASE4_RESOURCE_DATA) / "national_resource_stock.csv"

    district_totals: dict[str, float] = defaultdict(float)
    state_totals: dict[str, float] = defaultdict(float)
    national_totals: dict[str, float] = defaultdict(float)

    if district_file.exists():
        with district_file.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = str(row.get("resource_id") or "").strip()
                if not rid:
                    continue
                district_totals[rid] += float(row.get("quantity") or 0.0)

    if state_file.exists():
        with state_file.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = str(row.get("resource_id") or "").strip()
                if not rid:
                    continue
                state_totals[rid] += float(row.get("quantity") or 0.0)

    if national_file.exists():
        with national_file.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = str(row.get("resource_id") or "").strip()
                if not rid:
                    continue
                national_totals[rid] += float(row.get("quantity") or 0.0)

    return dict(district_totals), dict(state_totals), dict(national_totals)


def _jain(values: list[float]) -> float | None:
    arr = [max(0.0, float(v)) for v in values]
    if not arr:
        return None
    numerator = sum(arr) ** 2
    denominator = float(len(arr)) * sum(v * v for v in arr)
    if denominator <= 1e-12:
        return None
    return float(numerator / denominator)


def _fairness_metrics(db, run_id: int) -> dict[str, Any]:
    rows = db.query(
        Allocation.district_code,
        Allocation.state_code,
        Allocation.time,
        Allocation.allocated_quantity,
        Allocation.is_unmet,
    ).filter(Allocation.solver_run_id == int(run_id)).all()

    demand_by_district: dict[str, float] = defaultdict(float)
    alloc_by_district: dict[str, float] = defaultdict(float)

    demand_by_state: dict[str, float] = defaultdict(float)
    alloc_by_state: dict[str, float] = defaultdict(float)

    demand_by_time: dict[int, float] = defaultdict(float)
    alloc_by_time: dict[int, float] = defaultdict(float)

    for r in rows:
        district = str(r.district_code)
        state = str(r.state_code or "")
        t = int(r.time)
        qty = float(r.allocated_quantity or 0.0)

        demand_by_district[district] += qty
        demand_by_state[state] += qty
        demand_by_time[t] += qty
        if not bool(r.is_unmet):
            alloc_by_district[district] += qty
            alloc_by_state[state] += qty
            alloc_by_time[t] += qty

    district_ratios = [
        (alloc_by_district.get(k, 0.0) / demand_by_district[k])
        for k in demand_by_district
        if demand_by_district[k] > 1e-9
    ]
    state_ratios = [
        (alloc_by_state.get(k, 0.0) / demand_by_state[k])
        for k in demand_by_state
        if demand_by_state[k] > 1e-9
    ]

    time_items = sorted(demand_by_time.items(), key=lambda x: x[0])
    early_values: list[float] = []
    late_values: list[float] = []
    if time_items:
        pivot = len(time_items) // 2
        for idx, (time_key, demand_val) in enumerate(time_items):
            ratio = (alloc_by_time.get(time_key, 0.0) / demand_val) if demand_val > 1e-9 else 1.0
            if idx <= pivot:
                early_values.append(ratio)
            else:
                late_values.append(ratio)

    district_jain = _jain(district_ratios)
    state_jain = _jain(state_ratios)
    district_gap = (max(district_ratios) - min(district_ratios)) if district_ratios else None
    state_gap = (max(state_ratios) - min(state_ratios)) if state_ratios else None

    early_avg = (sum(early_values) / len(early_values)) if early_values else None
    late_avg = (sum(late_values) / len(late_values)) if late_values else None

    fairness_flags: list[str] = []
    if district_jain is not None and district_jain < 0.85:
        fairness_flags.append("district_fairness_low")
    if state_jain is not None and state_jain < 0.80:
        fairness_flags.append("state_fairness_low")
    if district_gap is not None and district_gap > 0.45:
        fairness_flags.append("district_gap_high")
    if early_avg is not None and late_avg is not None and early_avg + 0.05 < late_avg:
        fairness_flags.append("time_index_priority_violation")

    return {
        "district_ratio_jain": district_jain,
        "state_ratio_jain": state_jain,
        "district_ratio_gap": district_gap,
        "state_ratio_gap": state_gap,
        "time_service_early_avg": early_avg,
        "time_service_late_avg": late_avg,
        "district_entities": len(district_ratios),
        "state_entities": len(state_ratios),
        "fairness_flags": fairness_flags,
    }


def _scope_and_unmet_metrics(db, run_id: int) -> dict[str, Any]:
    rows = db.query(
        Allocation.resource_id,
        Allocation.allocated_quantity,
        Allocation.is_unmet,
        Allocation.supply_level,
        Allocation.allocation_source_scope,
    ).filter(Allocation.solver_run_id == int(run_id)).all()

    resources_used: set[str] = set()
    total_alloc = 0.0
    total_unmet = 0.0
    by_scope_qty = {
        "district": 0.0,
        "state": 0.0,
        "neighbor_state": 0.0,
        "national": 0.0,
    }

    for r in rows:
        rid = str(r.resource_id)
        resources_used.add(rid)
        qty = float(r.allocated_quantity or 0.0)
        if bool(r.is_unmet):
            total_unmet += qty
            continue
        total_alloc += qty
        level = str(r.supply_level or "district").lower()
        scope = str(r.allocation_source_scope or "district").lower()
        if scope in by_scope_qty:
            by_scope_qty[scope] += qty
        elif level in by_scope_qty:
            by_scope_qty[level] += qty
        else:
            by_scope_qty["district"] += qty

    return {
        "resources_used": sorted(resources_used),
        "allocated_total": total_alloc,
        "unmet_total": total_unmet,
        "scope_allocations": by_scope_qty,
        "auto_state_called": by_scope_qty["state"] > 1e-9,
        "auto_neighbor_called": by_scope_qty["neighbor_state"] > 1e-9,
        "auto_national_called": by_scope_qty["national"] > 1e-9,
    }


def _unmet_reason(
    run_metrics: dict[str, Any],
    district_totals: dict[str, float],
    state_totals: dict[str, float],
    national_totals: dict[str, float],
    scenario_state_override_total: float,
    scenario_national_override_total: float,
) -> dict[str, Any]:
    resources = list(run_metrics.get("resources_used") or [])

    district_stock = sum(float(district_totals.get(r, 0.0)) for r in resources)
    state_stock = sum(float(state_totals.get(r, 0.0)) for r in resources)
    national_stock = sum(float(national_totals.get(r, 0.0)) for r in resources)

    total_supply_est = district_stock + state_stock + national_stock + scenario_state_override_total + scenario_national_override_total
    total_demand = float(run_metrics.get("allocated_total", 0.0)) + float(run_metrics.get("unmet_total", 0.0))
    unmet = float(run_metrics.get("unmet_total", 0.0))

    reason = "none"
    if unmet > 1e-9:
        if total_demand > total_supply_est * 1.01:
            reason = "unmet_due_to_total_supply_limit"
        elif not bool(run_metrics.get("auto_state_called") or run_metrics.get("auto_neighbor_called") or run_metrics.get("auto_national_called")):
            reason = "unmet_without_cross_scope_supply"
        else:
            reason = "unmet_with_cross_scope_supply_likely_time_or_network_constraint"

    return {
        "reason": reason,
        "total_demand": total_demand,
        "estimated_total_supply": total_supply_est,
        "estimated_district_stock": district_stock,
        "estimated_state_stock": state_stock,
        "estimated_national_stock": national_stock,
        "scenario_state_override_total": scenario_state_override_total,
        "scenario_national_override_total": scenario_national_override_total,
    }


def _manual_aid_acceptance_admin_simulation(db, run_id: int) -> dict[str, Any]:
    created_count = int(create_requests_from_unmet_allocations(db, int(run_id)) or 0)

    run_row = db.query(SolverRun).filter(SolverRun.id == int(run_id)).first()
    if run_row is None:
        return {
            "aid_requests_created": created_count,
            "offers_created": 0,
            "offers_accepted": 0,
            "accepted_quantity": 0.0,
        }

    query = db.query(MutualAidRequest).filter(
        MutualAidRequest.status.in_(["open", "partially_filled"]),
    )
    if run_row.started_at is not None:
        query = query.filter(MutualAidRequest.created_at >= run_row.started_at)
    reqs = query.order_by(MutualAidRequest.id.asc()).all()

    offers_created = 0
    offers_accepted = 0
    accepted_quantity = 0.0

    for req in reqs:
        accepted_existing = float(
            db.query(func.coalesce(func.sum(MutualAidOffer.quantity_offered), 0.0)).filter(
                MutualAidOffer.request_id == int(req.id),
                MutualAidOffer.status == "accepted",
            ).scalar()
            or 0.0
        )
        remaining = max(0.0, float(req.quantity_requested or 0.0) - accepted_existing)
        if remaining <= 1e-9:
            continue

        candidate_states = get_candidate_states(db, requesting_state=str(req.requesting_state), limit=10)
        for item in candidate_states:
            offering_state = str(item.get("state_code") or "").strip()
            if not offering_state or offering_state == str(req.requesting_state):
                continue

            existing_offer = db.query(MutualAidOffer).filter(
                MutualAidOffer.request_id == int(req.id),
                MutualAidOffer.offering_state == offering_state,
                MutualAidOffer.status.in_(["pending", "accepted"]),
            ).first()
            if existing_offer is not None:
                continue

            offer_qty = max(1.0, float(remaining * 0.6))
            try:
                offer = create_mutual_aid_offer(
                    db=db,
                    request_id=int(req.id),
                    offering_state=offering_state,
                    quantity_offered=float(offer_qty),
                    cap_quantity=float(offer_qty),
                )
                offers_created += 1
            except Exception:
                db.rollback()
                continue

            try:
                responded = respond_to_offer(
                    db=db,
                    offer_id=int(offer.id),
                    decision="accepted",
                    actor_state=str(req.requesting_state),
                )
                if str(responded.status or "").lower() == "accepted":
                    offers_accepted += 1
                    accepted_quantity += float(offer.quantity_offered or 0.0)
            except Exception:
                db.rollback()
            break

    return {
        "aid_requests_created": created_count,
        "offers_created": int(offers_created),
        "offers_accepted": int(offers_accepted),
        "accepted_quantity": float(round(accepted_quantity, 4)),
    }


def _stress_variant(cycle: int, preset: str, state_codes: list[str]) -> dict[str, Any]:
    heavy_district = [14, 20, 28, 36, 44, 50]
    heavy_resources = [8, 12, 16, 20, 24]
    heavy_horizon = [3, 4, 5, 6, 8]

    payload = {
        "preset": str(preset),
        "seed": 20270000 + int(cycle * 31),
        "time_horizon": int(heavy_horizon[(cycle - 1) % len(heavy_horizon)]),
        "district_count": int(heavy_district[(cycle - 1) % len(heavy_district)]),
        "resource_count": int(heavy_resources[(cycle - 1) % len(heavy_resources)]),
        "stress_mode": True,
        "replace_existing": True,
    }

    if state_codes:
        width = min(8, max(3, 3 + (cycle % 4)))
        start = (cycle - 1) % len(state_codes)
        payload["state_codes"] = [str(state_codes[(start + i) % len(state_codes)]) for i in range(width)]

    return payload


def run_stress_certification(runs: int = 60, run_scope: str = "focused") -> dict[str, Any]:
    run_count = max(10, int(runs))
    scope_mode = str(run_scope or "focused").strip().lower()
    if scope_mode not in {"focused", "full"}:
        scope_mode = "focused"

    presets = ["very_low", "low", "medium", "high", "extreme"]
    district_totals, state_totals, national_totals = _load_scope_stock_totals()

    client = TestClient(app, raise_server_exceptions=False)
    db = SessionLocal()

    login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    if login.status_code != 200:
        raise RuntimeError(f"Admin login failed: {login.status_code} {login.text}")
    token = login.json().get("access_token")
    if not token:
        raise RuntimeError("Admin token missing")
    headers = {"Authorization": f"Bearer {token}"}

    states_resp = client.get("/metadata/states", headers=headers)
    state_codes: list[str] = []
    if states_resp.status_code == 200:
        state_codes = [str(x.get("state_code")) for x in (states_resp.json() or []) if x.get("state_code")]

    cycles: list[dict[str, Any]] = []

    try:
        for i in range(1, run_count + 1):
            preset = presets[(i - 1) % len(presets)]
            cycle: dict[str, Any] = {
                "cycle": i,
                "preset": preset,
                "started_at": _now(),
                "run_scope": scope_mode,
                "scenario_name": f"AUTO_ADMIN_60_STRESS_{i}_{datetime.now(timezone.utc).strftime('%H%M%S')}",
                "scenario_id": None,
                "create_status": None,
                "preview_status": None,
                "apply_status": None,
                "run_status": None,
                "run_detail": None,
                "run_id": None,
                "summary_status": None,
                "followup_run_status": None,
                "followup_run_id": None,
                "followup_summary_status": None,
                "revert_status": None,
                "verify_status": None,
                "followup_revert_status": None,
                "followup_verify_status": None,
                "verify_ok": False,
                "verify_net_total": None,
                "verify_debit_total": None,
                "verify_revert_total": None,
                "followup_verify_ok": None,
                "followup_verify_net_total": None,
                "manual_aid": {},
                "fairness": {},
                "unmet_analysis": {},
                "followup_fairness": {},
                "followup_unmet_analysis": {},
                "variant": {},
                "pass": False,
                "notes": [],
                "finished_at": None,
            }

            try:
                create_resp = client.post("/admin/scenarios", headers=headers, json={"name": cycle["scenario_name"]})
                cycle["create_status"] = int(create_resp.status_code)
                if create_resp.status_code != 200:
                    cycle["notes"].append("scenario_create_failed")
                    cycles.append(cycle)
                    continue

                scenario_id = int((_safe_json(create_resp).get("id") or 0))
                cycle["scenario_id"] = scenario_id

                variant = _stress_variant(i, preset, state_codes=state_codes)
                cycle["variant"] = variant

                preview_resp = client.post(
                    f"/admin/scenarios/{scenario_id}/randomizer/preview",
                    headers=headers,
                    json=variant,
                )
                cycle["preview_status"] = int(preview_resp.status_code)
                preview_payload = _safe_json(preview_resp)
                cycle["preview"] = {
                    "ratio": preview_payload.get("demand_ratio_vs_baseline"),
                    "row_count": preview_payload.get("row_count"),
                    "warnings": len(preview_payload.get("guardrail_warnings") or []),
                }

                apply_resp = client.post(
                    f"/admin/scenarios/{scenario_id}/randomizer/apply",
                    headers=headers,
                    json=variant,
                )
                cycle["apply_status"] = int(apply_resp.status_code)
                if apply_resp.status_code != 200:
                    cycle["notes"].append("randomizer_apply_failed")
                    cycles.append(cycle)
                    continue

                run_resp = client.post(
                    f"/admin/scenarios/{scenario_id}/run",
                    headers=headers,
                    json={"scope_mode": scope_mode},
                )
                cycle["run_status"] = int(run_resp.status_code)
                if run_resp.status_code != 200:
                    cycle["notes"].append("scenario_run_failed")
                    cycle["run_detail"] = _safe_json(run_resp)

                runs_resp = client.get(f"/admin/scenarios/{scenario_id}/runs", headers=headers)
                cycle["runs_status"] = int(runs_resp.status_code)
                runs_arr = runs_resp.json() if runs_resp.status_code == 200 else []
                if runs_arr:
                    cycle["run_id"] = int((runs_arr[0] or {}).get("id") or 0)
                else:
                    cycle["notes"].append("no_run_id")
                    cycles.append(cycle)
                    continue

                run_id = int(cycle["run_id"])

                summary_resp = client.get(f"/admin/scenarios/{scenario_id}/runs/{run_id}/summary", headers=headers)
                cycle["summary_status"] = int(summary_resp.status_code)
                summary_payload = _safe_json(summary_resp) if summary_resp.status_code == 200 else {}
                cycle["summary"] = {
                    "totals": summary_payload.get("totals"),
                }

                fairness = _fairness_metrics(db, run_id=run_id)
                cycle["fairness"] = fairness

                run_metrics = _scope_and_unmet_metrics(db, run_id=run_id)

                scenario_state_override_total = float(
                    db.query(func.coalesce(func.sum(ScenarioStateStock.quantity), 0.0)).filter(
                        ScenarioStateStock.scenario_id == int(scenario_id)
                    ).scalar()
                    or 0.0
                )
                scenario_national_override_total = float(
                    db.query(func.coalesce(func.sum(ScenarioNationalStock.quantity), 0.0)).filter(
                        ScenarioNationalStock.scenario_id == int(scenario_id)
                    ).scalar()
                    or 0.0
                )

                cycle["unmet_analysis"] = {
                    **run_metrics,
                    **_unmet_reason(
                        run_metrics=run_metrics,
                        district_totals=district_totals,
                        state_totals=state_totals,
                        national_totals=national_totals,
                        scenario_state_override_total=scenario_state_override_total,
                        scenario_national_override_total=scenario_national_override_total,
                    ),
                }

                cycle["manual_aid"] = _manual_aid_acceptance_admin_simulation(db, run_id=run_id)

                offers_accepted = int((cycle.get("manual_aid") or {}).get("offers_accepted") or 0)
                if offers_accepted > 0:
                    followup_resp = client.post(
                        f"/admin/scenarios/{scenario_id}/run",
                        headers=headers,
                        json={"scope_mode": scope_mode},
                    )
                    cycle["followup_run_status"] = int(followup_resp.status_code)
                    if followup_resp.status_code != 200:
                        cycle["notes"].append("followup_run_failed")

                    followup_runs_resp = client.get(f"/admin/scenarios/{scenario_id}/runs", headers=headers)
                    followup_runs_arr = followup_runs_resp.json() if followup_runs_resp.status_code == 200 else []
                    if followup_runs_arr:
                        newest_run_id = int((followup_runs_arr[0] or {}).get("id") or 0)
                        if newest_run_id and newest_run_id != run_id:
                            cycle["followup_run_id"] = newest_run_id

                    if cycle.get("followup_run_id"):
                        followup_run_id = int(cycle["followup_run_id"])

                        followup_summary_resp = client.get(
                            f"/admin/scenarios/{scenario_id}/runs/{followup_run_id}/summary",
                            headers=headers,
                        )
                        cycle["followup_summary_status"] = int(followup_summary_resp.status_code)

                        cycle["followup_fairness"] = _fairness_metrics(db, run_id=followup_run_id)
                        followup_metrics = _scope_and_unmet_metrics(db, run_id=followup_run_id)
                        cycle["followup_unmet_analysis"] = {
                            **followup_metrics,
                            **_unmet_reason(
                                run_metrics=followup_metrics,
                                district_totals=district_totals,
                                state_totals=state_totals,
                                national_totals=national_totals,
                                scenario_state_override_total=scenario_state_override_total,
                                scenario_national_override_total=scenario_national_override_total,
                            ),
                        }
                    else:
                        cycle["notes"].append("followup_run_id_missing")

                revert_resp = client.post(
                    f"/admin/scenarios/{scenario_id}/revert-effects",
                    headers=headers,
                    json={"run_id": run_id},
                )
                cycle["revert_status"] = int(revert_resp.status_code)
                if revert_resp.status_code != 200:
                    cycle["notes"].append("revert_failed")

                verify_resp = client.get(
                    f"/admin/scenarios/{scenario_id}/revert-effects/verify?run_id={run_id}",
                    headers=headers,
                )
                cycle["verify_status"] = int(verify_resp.status_code)
                if verify_resp.status_code == 200:
                    verify_payload = _safe_json(verify_resp)
                    cycle["verify_ok"] = bool(verify_payload.get("ok"))
                    cycle["verify_net_total"] = verify_payload.get("net_total")
                    cycle["verify_debit_total"] = verify_payload.get("debit_total")
                    cycle["verify_revert_total"] = verify_payload.get("revert_total")
                    if not cycle["verify_ok"]:
                        cycle["notes"].append("revert_verify_not_zero")
                else:
                    cycle["notes"].append("revert_verify_failed")

                if cycle.get("followup_run_id"):
                    followup_run_id = int(cycle["followup_run_id"])
                    followup_revert_resp = client.post(
                        f"/admin/scenarios/{scenario_id}/revert-effects",
                        headers=headers,
                        json={"run_id": followup_run_id},
                    )
                    cycle["followup_revert_status"] = int(followup_revert_resp.status_code)
                    if followup_revert_resp.status_code != 200:
                        cycle["notes"].append("followup_revert_failed")

                    followup_verify_resp = client.get(
                        f"/admin/scenarios/{scenario_id}/revert-effects/verify?run_id={followup_run_id}",
                        headers=headers,
                    )
                    cycle["followup_verify_status"] = int(followup_verify_resp.status_code)
                    if followup_verify_resp.status_code == 200:
                        followup_verify_payload = _safe_json(followup_verify_resp)
                        cycle["followup_verify_ok"] = bool(followup_verify_payload.get("ok"))
                        cycle["followup_verify_net_total"] = followup_verify_payload.get("net_total")
                        if not cycle["followup_verify_ok"]:
                            cycle["notes"].append("followup_revert_verify_not_zero")
                    else:
                        cycle["notes"].append("followup_revert_verify_failed")

                cycle["pass"] = (
                    cycle.get("create_status") == 200
                    and cycle.get("apply_status") == 200
                    and cycle.get("run_status") == 200
                    and cycle.get("summary_status") == 200
                    and cycle.get("revert_status") == 200
                    and cycle.get("verify_status") == 200
                    and cycle.get("verify_ok") is True
                    and (
                        cycle.get("followup_run_id") is None
                        or (
                            cycle.get("followup_run_status") == 200
                            and cycle.get("followup_summary_status") == 200
                            and cycle.get("followup_revert_status") == 200
                            and cycle.get("followup_verify_status") == 200
                            and cycle.get("followup_verify_ok") is True
                        )
                    )
                )

                if not cycle["pass"] and not cycle["notes"]:
                    cycle["notes"].append("unknown_failure")

            except Exception as exc:
                cycle["notes"].append(f"unexpected_exception:{type(exc).__name__}")
                cycle["notes"].append(str(exc))
            finally:
                cycle["finished_at"] = _now()
                cycles.append(cycle)

        pass_count = sum(1 for c in cycles if bool(c.get("pass")))
        fail_count = len(cycles) - pass_count

        return {
            "generated_at": _now(),
            "runs_requested": run_count,
            "runs_executed": len(cycles),
            "run_scope": scope_mode,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "overall_status": "PASS" if fail_count == 0 else "FAIL",
            "cycles": cycles,
        }
    finally:
        db.close()


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    json_path, md_path = _report_paths()
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Admin 60-Cycle Stress Certification Report",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Overall: **{report.get('overall_status')}**",
        f"Runs: {report.get('runs_executed')} (Pass={report.get('pass_count')}, Fail={report.get('fail_count')})",
        f"Scope: {report.get('run_scope')}",
        "",
        "## Cycle Summary",
        "",
        "|Cycle|Preset|Run|FollowupRun|Pass|RunStatus|Unmet|AutoState|AutoNeighbor|AutoNational|FollowupAutoState|FollowupAutoNeighbor|FollowupAutoNational|ManualAidAccepted|DistrictJain|StateJain|RevertNet|Notes|",
        "|---:|---|---:|---:|---|---:|---:|---|---|---|---|---|---|---:|---:|---:|---:|---|",
    ]

    for c in report.get("cycles", []):
        unmet_total = ((c.get("unmet_analysis") or {}).get("unmet_total") or 0.0)
        lines.append(
            "| {cycle} | {preset} | {run_id} | {followup_run_id} | {result} | {run_status} | {unmet} | {state} | {neighbor} | {national} | {f_state} | {f_neighbor} | {f_national} | {aid} | {dj} | {sj} | {net} | {notes} |".format(
                cycle=c.get("cycle"),
                preset=c.get("preset"),
                run_id=c.get("run_id") or 0,
                followup_run_id=c.get("followup_run_id") or 0,
                result=("PASS" if c.get("pass") else "FAIL"),
                run_status=c.get("run_status") or 0,
                unmet=round(float(unmet_total), 4),
                state=("Y" if (c.get("unmet_analysis") or {}).get("auto_state_called") else "N"),
                neighbor=("Y" if (c.get("unmet_analysis") or {}).get("auto_neighbor_called") else "N"),
                national=("Y" if (c.get("unmet_analysis") or {}).get("auto_national_called") else "N"),
                f_state=("Y" if (c.get("followup_unmet_analysis") or {}).get("auto_state_called") else "N"),
                f_neighbor=("Y" if (c.get("followup_unmet_analysis") or {}).get("auto_neighbor_called") else "N"),
                f_national=("Y" if (c.get("followup_unmet_analysis") or {}).get("auto_national_called") else "N"),
                aid=int((c.get("manual_aid") or {}).get("offers_accepted") or 0),
                dj=round(float((c.get("fairness") or {}).get("district_ratio_jain") or 0.0), 4),
                sj=round(float((c.get("fairness") or {}).get("state_ratio_jain") or 0.0), 4),
                net=round(float(c.get("verify_net_total") or 0.0), 4),
                notes=(", ".join(c.get("notes") or []) or "-"),
            )
        )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Admin stress certification with fairness/manual-aid checks")
    parser.add_argument("--runs", type=int, default=60, help="Number of cycles to execute")
    parser.add_argument("--run-scope", type=str, default="focused", choices=["focused", "full"], help="Scenario run scope")
    args = parser.parse_args()

    report = run_stress_certification(runs=int(args.runs), run_scope=str(args.run_scope))
    json_path, md_path = write_reports(report)

    print(
        json.dumps(
            {
                "overall_status": report.get("overall_status"),
                "runs_executed": report.get("runs_executed"),
                "pass_count": report.get("pass_count"),
                "fail_count": report.get("fail_count"),
                "json_report": str(json_path),
                "md_report": str(md_path),
            }
        )
    )


if __name__ == "__main__":
    main()
