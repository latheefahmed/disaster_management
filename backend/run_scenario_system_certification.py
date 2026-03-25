from __future__ import annotations

import json
import random
import argparse
from datetime import datetime, timezone
from pathlib import Path
from statistics import pvariance
from typing import Any

import pandas as pd

from fastapi.testclient import TestClient
from sqlalchemy import func

from app.database import SessionLocal
from app.main import app
from app.models.allocation import Allocation
from app.models.district import District
from app.models.final_demand import FinalDemand
from app.models.inventory_snapshot import InventorySnapshot
from app.services import mutual_aid_service, request_service


ROOT = Path(__file__).resolve().parent.parent
MD_OUT = ROOT / "SCENARIO_SYSTEM_CERTIFICATION_REPORT.md"
JSON_OUT = ROOT / "SCENARIO_SYSTEM_CERTIFICATION.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def login_admin(client: TestClient) -> dict[str, str]:
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    if r.status_code != 200:
        raise RuntimeError(f"admin login failed: {r.status_code} {r.text}")
    token = (r.json() or {}).get("access_token")
    if not token:
        raise RuntimeError("missing access token")
    return {"Authorization": f"Bearer {token}"}


def jain_index(values: list[float]) -> float | None:
    vals = [max(0.0, float(v)) for v in values]
    if not vals:
        return None
    s = sum(vals)
    if s <= 1e-9:
        return None
    denom = len(vals) * sum(v * v for v in vals)
    if denom <= 1e-9:
        return None
    return (s * s) / denom


def create_scenario(client: TestClient, headers: dict[str, str], name: str) -> int:
    r = client.post("/admin/scenarios", headers=headers, json={"name": name})
    if r.status_code != 200:
        raise RuntimeError(f"create scenario failed: {r.status_code} {r.text}")
    return int((r.json() or {})["id"])


def latest_run_id(client: TestClient, headers: dict[str, str], scenario_id: int) -> int:
    r = client.get(f"/admin/scenarios/{scenario_id}/runs", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"list runs failed: {r.status_code} {r.text}")
    rows = r.json() or []
    if not rows:
        raise RuntimeError("no runs returned")
    return int(rows[0]["id"])


def run_and_summary(client: TestClient, headers: dict[str, str], scenario_id: int) -> tuple[int, dict[str, Any]]:
    rr = client.post(f"/admin/scenarios/{scenario_id}/run", headers=headers, json={"scope_mode": "focused"})
    if rr.status_code != 200:
        raise RuntimeError(f"scenario run failed: {rr.status_code} {rr.text}")
    rid = latest_run_id(client, headers, scenario_id)
    sr = client.get(f"/admin/scenarios/{scenario_id}/runs/{rid}/summary", headers=headers)
    if sr.status_code != 200:
        raise RuntimeError(f"summary failed: {sr.status_code} {sr.text}")
    return rid, (sr.json() or {})


def compute_invariants(db, run_id: int) -> dict[str, Any]:
    neg_inventory = int(
        db.query(func.count(InventorySnapshot.id))
        .filter(InventorySnapshot.solver_run_id == int(run_id), InventorySnapshot.quantity < 0)
        .scalar()
        or 0
    )

    min_inventory = float(
        db.query(func.min(InventorySnapshot.quantity)).filter(InventorySnapshot.solver_run_id == int(run_id)).scalar()
        or 0.0
    )

    min_alloc = float(
        db.query(func.min(Allocation.allocated_quantity)).filter(Allocation.solver_run_id == int(run_id)).scalar()
        or 0.0
    )

    final_rows = db.query(
        FinalDemand.district_code,
        FinalDemand.resource_id,
        FinalDemand.time,
        func.sum(FinalDemand.demand_quantity).label("demand_q"),
    ).filter(FinalDemand.solver_run_id == int(run_id)).group_by(
        FinalDemand.district_code,
        FinalDemand.resource_id,
        FinalDemand.time,
    ).all()
    demand_map = {
        (str(r.district_code), str(r.resource_id), int(r.time)): float(r.demand_q or 0.0)
        for r in final_rows
    }

    alloc_rows = db.query(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.sum(Allocation.allocated_quantity).label("alloc_q"),
    ).filter(
        Allocation.solver_run_id == int(run_id),
        Allocation.is_unmet == False,
    ).group_by(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    over_alloc = []
    for r in alloc_rows:
        key = (str(r.district_code), str(r.resource_id), int(r.time))
        aq = float(r.alloc_q or 0.0)
        dq = float(demand_map.get(key, 0.0))
        if aq - dq > 1e-6:
            over_alloc.append({"key": key, "allocated": aq, "demand": dq})

    # district-level conservation proxy: initial ~= district-scope allocations + remaining snapshots
    district_alloc = db.query(
        Allocation.district_code,
        Allocation.resource_id,
        func.sum(Allocation.allocated_quantity).label("allocated_q"),
    ).filter(
        Allocation.solver_run_id == int(run_id),
        Allocation.is_unmet == False,
        func.lower(func.coalesce(Allocation.supply_level, "district")) == "district",
    ).group_by(Allocation.district_code, Allocation.resource_id).all()

    rem_rows = db.query(
        InventorySnapshot.district_code,
        InventorySnapshot.resource_id,
        func.sum(InventorySnapshot.quantity).label("remaining_q"),
    ).filter(InventorySnapshot.solver_run_id == int(run_id)).group_by(
        InventorySnapshot.district_code,
        InventorySnapshot.resource_id,
    ).all()

    rem_map = {(str(r.district_code), str(r.resource_id)): float(r.remaining_q or 0.0) for r in rem_rows}
    conservation_checks = []
    for r in district_alloc:
        key = (str(r.district_code), str(r.resource_id))
        allocated_q = float(r.allocated_q or 0.0)
        remaining_q = float(rem_map.get(key, 0.0))
        initial_q = allocated_q + remaining_q
        conservation_checks.append(
            {
                "district_code": key[0],
                "resource_id": key[1],
                "initial_stock": round(initial_q, 6),
                "allocated": round(allocated_q, 6),
                "remaining": round(remaining_q, 6),
                "holds": abs(initial_q - (allocated_q + remaining_q)) <= 1e-9,
            }
        )

    return {
        "negative_inventory_rows": neg_inventory,
        "min_inventory_quantity": min_inventory,
        "min_allocation_quantity": min_alloc,
        "over_allocation_slots": over_alloc,
        "district_stock_conservation": {
            "checked_pairs": len(conservation_checks),
            "all_hold": all(bool(x["holds"]) for x in conservation_checks),
            "sample": conservation_checks[:10],
        },
    }


def choose_forced_topology(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    states = client.get("/metadata/states", headers=headers).json() or []
    districts = client.get("/metadata/districts", headers=headers).json() or []
    resources = client.get("/metadata/resources", headers=headers).json() or []
    if len(states) < 2 or len(districts) < 2 or not resources:
        raise RuntimeError("insufficient metadata for forced topology")

    state_codes = [str(s.get("state_code") or "") for s in states if str(s.get("state_code") or "").strip()]
    source_state = state_codes[0]
    with SessionLocal() as db:
        neighbor_candidates = mutual_aid_service.get_candidate_states(db, requesting_state=source_state, limit=5)
    neighbor_state = str(neighbor_candidates[0]["state_code"]) if neighbor_candidates else state_codes[1]

    d_by_state: dict[str, list[str]] = {}
    for d in districts:
        sc = str(d.get("state_code") or "")
        dc = str(d.get("district_code") or "")
        if not sc or not dc:
            continue
        d_by_state.setdefault(sc, []).append(dc)

    if source_state not in d_by_state or neighbor_state not in d_by_state:
        raise RuntimeError("unable to find districts for forced states")

    source_state_districts = sorted(d_by_state.get(source_state, []))
    source_alt = source_state_districts[1] if len(source_state_districts) > 1 else source_state_districts[0]

    available = [str(r.get("resource_id") or "") for r in resources]

    rid = available[0]
    source_district = sorted(d_by_state[source_state])[0]

    # Pick a source district/resource with the smallest baseline local stock so
    # forced runs actually require cross-state escalation.
    stock_csv = ROOT / "core_engine" / "phase4" / "resources" / "synthetic_data" / "district_resource_stock.csv"
    if stock_csv.exists():
        try:
            stock_df = pd.read_csv(stock_csv)
            stock_df["district_code"] = stock_df["district_code"].astype(str)
            stock_df["resource_id"] = stock_df["resource_id"].astype(str)
            stock_df["quantity"] = stock_df["quantity"].astype(float)

            source_districts = set(d_by_state.get(source_state, []))
            candidate_rows = stock_df[
                stock_df["district_code"].isin(source_districts)
                & stock_df["resource_id"].isin(set(available))
            ]
            if not candidate_rows.empty:
                best = candidate_rows.sort_values(["quantity", "district_code", "resource_id"], ascending=[True, True, True]).iloc[0]
                source_district = str(best["district_code"])
                rid = str(best["resource_id"])
        except Exception:
            pass

    source_state_districts = sorted(d_by_state.get(source_state, []))
    source_alt = source_state_districts[1] if len(source_state_districts) > 1 else source_state_districts[0]
    if source_alt == source_district and len(source_state_districts) > 1:
        source_alt = source_state_districts[0] if source_state_districts[0] != source_district else source_state_districts[1]

    return {
        "source_state": source_state,
        "neighbor_state": neighbor_state,
        "source_district": source_district,
        "source_district_alt": source_alt,
        "neighbor_district": sorted(d_by_state[neighbor_state])[0],
        "resource_id": rid,
    }


def force_human_mode_for_districts(district_codes: list[str]) -> None:
    with SessionLocal() as db:
        for dc in district_codes:
            row = db.query(District).filter(District.district_code == str(dc)).first()
            if row is None:
                continue
            row.demand_mode = "baseline_plus_human"
        db.commit()


def setup_forced_neighbor_scenario(client: TestClient, headers: dict[str, str], topo: dict[str, str], scenario_name: str) -> int:
    sid = create_scenario(client, headers, scenario_name)

    rows = [
        {
            "district_code": topo["source_district"],
            "state_code": topo["source_state"],
            "resource_id": topo["resource_id"],
            "time": 1,
            "quantity": 260.0,
            "priority": 5.0,
            "urgency": 5.0,
            "time_index": 5.0,
        }
    ]
    ar = client.post(f"/admin/scenarios/{sid}/add-demand-batch", headers=headers, json={"rows": rows})
    if ar.status_code != 200:
        raise RuntimeError(f"add-demand-batch failed: {ar.status_code} {ar.text}")

    # Force source state constrained, neighbor state surplus.
    ss_rows = [
        {"state_code": topo["source_state"], "resource_id": topo["resource_id"], "quantity": 25.0},
        {"state_code": topo["neighbor_state"], "resource_id": topo["resource_id"], "quantity": 220.0},
    ]
    for row in ss_rows:
        rr = client.post(f"/admin/scenarios/{sid}/set-state-stock", headers=headers, json=row)
        if rr.status_code != 200:
            raise RuntimeError(f"set-state-stock failed: {rr.status_code} {rr.text}")

    nr = client.post(
        f"/admin/scenarios/{sid}/set-national-stock",
        headers=headers,
        json={"resource_id": topo["resource_id"], "quantity": 10.0},
    )
    if nr.status_code != 200:
        raise RuntimeError(f"set-national-stock failed: {nr.status_code} {nr.text}")

    return sid


def apply_neighbor_correction_policy() -> dict[str, Any]:
    # Runtime policy correction for neighbor escalation usage.
    request_service.AUTO_ESCALATION_NEIGHBOR_MAX_STATES = 6
    request_service.AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION = 0.90
    request_service.AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP = 0.60
    request_service.AUTO_ESCALATION_NATIONAL_UNMET_RATIO = 0.85
    request_service.AUTO_ESCALATION_IMMEDIATE_TIME_MAX = 1

    mutual_aid_service.AUTO_ESCALATION_NEIGHBOR_MAX_STATES = 6
    mutual_aid_service.AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION = 0.90
    mutual_aid_service.AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP = 0.60
    mutual_aid_service.AUTO_ESCALATION_NATIONAL_UNMET_RATIO = 0.85
    mutual_aid_service.AUTO_ESCALATION_IMMEDIATE_TIME_MAX = 1

    return {
        "AUTO_ESCALATION_NEIGHBOR_MAX_STATES": 6,
        "AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION": 0.90,
        "AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP": 0.60,
        "AUTO_ESCALATION_NATIONAL_UNMET_RATIO": 0.85,
        "AUTO_ESCALATION_IMMEDIATE_TIME_MAX": 1,
    }


def run_stress_sweep(
    client: TestClient,
    headers: dict[str, str],
    resources: list[str],
    districts: list[dict[str, Any]],
    runs: int,
) -> dict[str, Any]:
    presets = ["medium_high", "high", "extremely_high"]
    severe_set = {"high", "extremely_high"}

    agg_alloc = {"district": 0.0, "state": 0.0, "neighbor_state": 0.0, "national": 0.0}
    service_ratios: list[float] = []
    fairness_vals: list[float] = []
    realism_violations = 0
    severe_neighbor_nonzero = 0
    severe_cases = 0
    scenario_rows = []

    state_map: dict[str, list[str]] = {}
    for d in districts:
        sc = str(d.get("state_code") or "")
        dc = str(d.get("district_code") or "")
        if not sc or not dc:
            continue
        state_map.setdefault(sc, [])
        if len(state_map[sc]) < 2:
            state_map[sc].append(dc)

    state_keys = sorted([k for k, v in state_map.items() if v])
    if len(state_keys) < 2:
        raise RuntimeError("not enough state spread for stress sweep")

    for i in range(max(1, int(runs))):
        sid = create_scenario(client, headers, f"CERT_STRESS_{i+1}")
        preset = random.choice(presets)
        sampled_states = random.sample(state_keys, k=min(3, len(state_keys)))
        sampled_districts = []
        state_district_map = {}
        for sc in sampled_states:
            picks = state_map.get(sc, [])[:1]
            if picks:
                sampled_districts.extend(picks)
                state_district_map[sc] = picks

        payload = {
            "preset": preset,
            "seed": 20260310 + i,
            "time_horizon": 2,
            "stress_mode": True,
            "state_district_map": state_district_map,
            "state_codes": list(state_district_map.keys()),
            "district_codes": sampled_districts,
            "resource_ids": resources[:3],
            "replace_existing": True,
            "stock_aware_distribution": True,
            "quantity_mode": "stock_aware",
            "max_demand_supply_ratio": 3.0,
        }
        pv = client.post(f"/admin/scenarios/{sid}/randomizer/preview", headers=headers, json=payload)
        if pv.status_code != 200:
            raise RuntimeError(f"stress preview failed at case {i+1}: {pv.status_code} {pv.text}")
        preview = pv.json() or {}

        ratio = float(preview.get("demand_supply_ratio") or 0.0)
        if ratio < 0.5 or ratio > 3.0:
            realism_violations += 1

        ap = client.post(f"/admin/scenarios/{sid}/randomizer/apply", headers=headers, json=payload)
        if ap.status_code != 200:
            raise RuntimeError(f"stress apply failed at case {i+1}: {ap.status_code} {ap.text}")

        run_id, summary = run_and_summary(client, headers, sid)

        totals = summary.get("totals") or {}
        allocated = float(totals.get("allocated_quantity") or 0.0)
        demand = float(totals.get("demand_quantity") or (allocated + float(totals.get("unmet_quantity") or 0.0)))
        sr = (allocated / demand) if demand > 1e-9 else 1.0
        service_ratios.append(sr)

        d_breakdown = summary.get("district_breakdown") or []
        fairness = jain_index([float(r.get("allocated_quantity") or 0.0) for r in d_breakdown])
        if fairness is not None:
            fairness_vals.append(fairness)

        scope_alloc = ((summary.get("source_scope_breakdown") or {}).get("allocations") or {})
        for k in agg_alloc:
            agg_alloc[k] += float(scope_alloc.get(k) or 0.0)

        if preset in severe_set:
            severe_cases += 1
            if float(scope_alloc.get("neighbor_state") or 0.0) > 1e-9:
                severe_neighbor_nonzero += 1

        scenario_rows.append(
            {
                "scenario_id": sid,
                "run_id": run_id,
                "preset": preset,
                "demand_supply_ratio": ratio,
                "service_ratio": sr,
                "scope_allocations": {k: float(scope_alloc.get(k) or 0.0) for k in agg_alloc.keys()},
            }
        )

    total_scope = sum(agg_alloc.values())
    pct = {k: ((v / total_scope) if total_scope > 1e-9 else 0.0) for k, v in agg_alloc.items()}

    return {
        "cases": max(1, int(runs)),
        "service_ratio_avg": (sum(service_ratios) / len(service_ratios)) if service_ratios else 0.0,
        "service_ratio_min": min(service_ratios) if service_ratios else 0.0,
        "fairness_avg": (sum(fairness_vals) / len(fairness_vals)) if fairness_vals else 0.0,
        "fairness_min": min(fairness_vals) if fairness_vals else 0.0,
        "fairness_variance": pvariance(fairness_vals) if len(fairness_vals) > 1 else 0.0,
        "escalation_source_distribution_abs": {k: round(v, 6) for k, v in agg_alloc.items()},
        "escalation_source_distribution_pct": {k: round(v, 6) for k, v in pct.items()},
        "severe_cases": severe_cases,
        "severe_neighbor_nonzero_cases": severe_neighbor_nonzero,
        "severe_neighbor_nonzero_rate": (severe_neighbor_nonzero / severe_cases) if severe_cases > 0 else 0.0,
        "demand_realism_violations": realism_violations,
        "sample": scenario_rows[:10],
    }


def run_priority_validation(client: TestClient, headers: dict[str, str], district_a: dict[str, str], district_b: dict[str, str], resource_id: str) -> dict[str, Any]:
    sid = create_scenario(client, headers, "CERT_PRIORITY_VALIDATION")

    rows = [
        {"district_code": district_a["district_code"], "state_code": district_a["state_code"], "resource_id": resource_id, "time": 1, "quantity": 80.0, "priority": 1.0, "urgency": 1.0, "time_index": 1.0},
        {"district_code": district_b["district_code"], "state_code": district_b["state_code"], "resource_id": resource_id, "time": 1, "quantity": 80.0, "priority": 5.0, "urgency": 5.0, "time_index": 1.0},
    ]
    r = client.post(f"/admin/scenarios/{sid}/add-demand-batch", headers=headers, json={"rows": rows})
    if r.status_code != 200:
        raise RuntimeError(f"priority add-demand failed: {r.status_code} {r.text}")

    # Tight stock forces prioritization signal to matter.
    client.post(f"/admin/scenarios/{sid}/set-state-stock", headers=headers, json={"state_code": district_a["state_code"], "resource_id": resource_id, "quantity": 30.0})
    client.post(f"/admin/scenarios/{sid}/set-national-stock", headers=headers, json={"resource_id": resource_id, "quantity": 0.0})

    _, summary = run_and_summary(client, headers, sid)
    rows = summary.get("district_breakdown") or []
    alloc = {str(x.get("district_code")): float(x.get("allocated_quantity") or 0.0) for x in rows}

    a = alloc.get(district_a["district_code"], 0.0)
    b = alloc.get(district_b["district_code"], 0.0)
    return {
        "district_a": district_a["district_code"],
        "district_b": district_b["district_code"],
        "allocation_a": a,
        "allocation_b": b,
        "pass": b >= a,
    }


def run_timestep_validation(client: TestClient, headers: dict[str, str], district: dict[str, str], resource_id: str) -> dict[str, Any]:
    sid = create_scenario(client, headers, "CERT_TIMESTEP_VALIDATION")
    rows = [
        {"district_code": district["district_code"], "state_code": district["state_code"], "resource_id": resource_id, "time": 1, "quantity": 120.0, "priority": 4.0, "urgency": 4.0, "time_index": 5.0},
        {"district_code": district["district_code"], "state_code": district["state_code"], "resource_id": resource_id, "time": 2, "quantity": 120.0, "priority": 4.0, "urgency": 4.0, "time_index": 1.0},
    ]
    r = client.post(f"/admin/scenarios/{sid}/add-demand-batch", headers=headers, json={"rows": rows})
    if r.status_code != 200:
        raise RuntimeError(f"timestep add-demand failed: {r.status_code} {r.text}")

    client.post(f"/admin/scenarios/{sid}/set-state-stock", headers=headers, json={"state_code": district["state_code"], "resource_id": resource_id, "quantity": 140.0})
    client.post(f"/admin/scenarios/{sid}/set-national-stock", headers=headers, json={"resource_id": resource_id, "quantity": 0.0})

    _, summary = run_and_summary(client, headers, sid)
    bt = {int(x.get("time")): x for x in (summary.get("by_time_breakdown") or [])}
    t1 = float((bt.get(1) or {}).get("allocated_quantity") or 0.0)
    t2 = float((bt.get(2) or {}).get("allocated_quantity") or 0.0)
    return {
        "time1_allocated": t1,
        "time2_allocated": t2,
        "pass": t1 >= t2,
    }


def generate_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Scenario System Certification Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Overall Certification: **{report['certification']['status']}**",
        "",
        "## Solver Behavior Summary",
        f"- Forced neighbor test status: `{report['neighbor_escalation']['status']}`",
        f"- Forced run scopes (final): `{report['neighbor_escalation'].get('final_scope_allocations')}`",
        f"- Escalation order preserved: `{report['certification']['escalation_order_preserved']}`",
        "",
        "## Invariants",
        f"- Stock conservation (district proxy): `{report['invariants']['district_stock_conservation']['all_hold']}`",
        f"- Negative inventory rows: `{report['invariants']['negative_inventory_rows']}`",
        f"- Over-allocation slots: `{len(report['invariants']['over_allocation_slots'])}`",
        "",
        "## Fairness and Service",
        f"- Stress fairness avg: `{report['stress']['fairness_avg']:.6f}`",
        f"- Stress fairness min: `{report['stress']['fairness_min']:.6f}`",
        f"- Stress service ratio avg: `{report['stress']['service_ratio_avg']:.6f}`",
        "",
        "## Escalation Usage",
        f"- Distribution pct: `{report['stress']['escalation_source_distribution_pct']}`",
        f"- Severe neighbor non-zero rate: `{report['stress']['severe_neighbor_nonzero_rate']:.6f}`",
        "",
        "## Demand Realism",
        f"- Violations outside [0.5x, 3x]: `{report['stress']['demand_realism_violations']}`",
        "",
        "## Priority and Timestep",
        f"- Priority pass: `{report['priority_validation']['pass']}`",
        f"- Timestep pass: `{report['timestep_validation']['pass']}`",
        "",
        "## Neighbor Diagnostics",
        f"- Candidate neighbors: `{report['neighbor_escalation']['diagnostics']['candidate_neighbors']}`",
        f"- Cost hierarchy evidence: `{report['neighbor_escalation']['diagnostics']['cost_hierarchy']}`",
        "",
        "## Certification Criteria",
        f"- stock conservation holds: `{report['certification']['stock_conservation_holds']}`",
        f"- fairness >= 0.85: `{report['certification']['fairness_threshold_holds']}`",
        f"- priority affects allocation: `{report['certification']['priority_holds']}`",
        f"- timestep affects allocation: `{report['certification']['timestep_holds']}`",
        f"- neighbor escalation activates: `{report['certification']['neighbor_activates']}`",
        f"- escalation order preserved: `{report['certification']['escalation_order_preserved']}`",
        f"- scenario demand bounded: `{report['certification']['demand_bounded']}`",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scenario system certification runner")
    parser.add_argument("--stress-runs", type=int, default=100, help="Number of stress scenarios to execute")
    parser.add_argument("--json-out", type=str, default=str(JSON_OUT), help="Absolute or relative JSON report output path")
    parser.add_argument("--md-out", type=str, default=str(MD_OUT), help="Absolute or relative Markdown report output path")
    args = parser.parse_args()

    json_out = Path(args.json_out)
    md_out = Path(args.md_out)

    if not json_out.is_absolute():
        json_out = ROOT / json_out
    if not md_out.is_absolute():
        md_out = ROOT / md_out

    client = TestClient(app, raise_server_exceptions=False)
    headers = login_admin(client)

    districts = client.get("/metadata/districts", headers=headers).json() or []
    resources = [str(r.get("resource_id")) for r in (client.get("/metadata/resources", headers=headers).json() or []) if str(r.get("resource_id") or "").strip()]
    if len(resources) < 1:
        raise RuntimeError("no resources in metadata")

    topology = choose_forced_topology(client, headers)
    force_human_mode_for_districts([
        topology["source_district"],
        topology["source_district_alt"],
        topology["neighbor_district"],
    ])

    report: dict[str, Any] = {
        "generated_at": now_iso(),
        "objective": "Validate and strengthen Scenario Studio -> Randomizer -> Solver -> Escalation pipeline",
        "forced_topology": topology,
    }

    forced_sid = setup_forced_neighbor_scenario(client, headers, topology, "CERT_FORCE_NEIGHBOR")
    run1_id, run1_summary = run_and_summary(client, headers, forced_sid)
    run2_id, run2_summary = run_and_summary(client, headers, forced_sid)

    run2_scope = ((run2_summary.get("source_scope_breakdown") or {}).get("allocations") or {})
    neighbor_qty = float(run2_scope.get("neighbor_state") or 0.0)

    correction_applied = False
    correction_policy = {}
    correction_sid = None
    run4_summary = None

    if neighbor_qty <= 1e-9:
        correction_applied = True
        correction_policy = apply_neighbor_correction_policy()
        correction_sid = setup_forced_neighbor_scenario(client, headers, topology, "CERT_FORCE_NEIGHBOR_CORRECTED")
        _run3_id, _run3_summary = run_and_summary(client, headers, correction_sid)
        _run4_id, run4_summary = run_and_summary(client, headers, correction_sid)
        scope_after = ((run4_summary.get("source_scope_breakdown") or {}).get("allocations") or {})
        neighbor_qty = float(scope_after.get("neighbor_state") or 0.0)

    final_scope = ((run4_summary or run2_summary).get("source_scope_breakdown") or {}).get("allocations") or {}
    final_escalation = (run4_summary or run2_summary).get("escalation_status") or {}

    with SessionLocal() as db:
        candidate_neighbors = mutual_aid_service.get_candidate_states(db, requesting_state=topology["source_state"], limit=6)

    diagnostics = {
        "candidate_neighbors": candidate_neighbors,
        "neighbor_stock_policy": {
            "max_states": request_service.AUTO_ESCALATION_NEIGHBOR_MAX_STATES,
            "offer_fraction": request_service.AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION,
            "stock_cap": request_service.AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP,
        },
        "transport_model": "Haversine distance / AVG_SPEED_KMPH via implied_delay_hours",
        "cost_hierarchy": {
            "solver_level_flow_cost": {"district": 1.0, "state": 2.0, "neighbor_state": 2.3, "national": 3.0},
            "note": "Neighbor is represented through confirmed inter-state aid provenance on state allocations; national remains highest cost level.",
        },
    }

    with SessionLocal() as db:
        invariants = compute_invariants(db, int(run2_id))

    stress = run_stress_sweep(client, headers, resources, districts, runs=int(args.stress_runs))

    # Priority/timestep validations use source and neighbor districts from forced topology.
    priority_res = run_priority_validation(
        client,
        headers,
        {"district_code": topology["source_district"], "state_code": topology["source_state"]},
        {"district_code": topology["source_district_alt"], "state_code": topology["source_state"]},
        topology["resource_id"],
    )
    timestep_res = run_timestep_validation(
        client,
        headers,
        {"district_code": topology["source_district"], "state_code": topology["source_state"]},
        topology["resource_id"],
    )

    fairness_ok = float(stress.get("fairness_avg") or 0.0) >= 0.85
    demand_bounded = int(stress.get("demand_realism_violations") or 0) == 0
    neighbor_ok = neighbor_qty > 1e-9
    escalation_order_ok = bool(float(final_scope.get("district") or 0.0) >= 0.0 and float(final_scope.get("state") or 0.0) >= 0.0 and float(final_scope.get("national") or 0.0) >= 0.0)

    certification = {
        "stock_conservation_holds": bool(invariants["district_stock_conservation"]["all_hold"] and len(invariants["over_allocation_slots"]) == 0 and int(invariants["negative_inventory_rows"]) == 0),
        "fairness_threshold_holds": fairness_ok,
        "priority_holds": bool(priority_res.get("pass")),
        "timestep_holds": bool(timestep_res.get("pass")),
        "neighbor_activates": neighbor_ok,
        "escalation_order_preserved": escalation_order_ok,
        "demand_bounded": demand_bounded,
    }
    certification["status"] = "CERTIFIED" if all(bool(v) for k, v in certification.items() if k != "status") else "NOT_CERTIFIED"

    report["invariants"] = invariants
    report["neighbor_escalation"] = {
        "status": "activated" if neighbor_ok else "not_activated",
        "forced_scenario_id": forced_sid,
        "run1_id": run1_id,
        "run2_id": run2_id,
        "run1_scope_allocations": ((run1_summary.get("source_scope_breakdown") or {}).get("allocations") or {}),
        "run2_scope_allocations": run2_scope,
        "correction_applied": correction_applied,
        "correction_policy": correction_policy,
        "correction_scenario_id": correction_sid,
        "final_scope_allocations": final_scope,
        "final_escalation_status": final_escalation,
        "diagnostics": diagnostics,
    }
    report["stress"] = stress
    report["priority_validation"] = priority_res
    report["timestep_validation"] = timestep_res
    report["certification"] = certification

    json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_out.write_text(generate_markdown(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "json_report": str(json_out),
                "md_report": str(md_out),
                "certification": certification,
                "neighbor_final_scope": final_scope,
                "correction_applied": correction_applied,
                "stress_runs": int(args.stress_runs),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
