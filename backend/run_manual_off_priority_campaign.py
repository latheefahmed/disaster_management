from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

BASE = "http://127.0.0.1:8000"
DISTRICT_USER = ("district_603", "pw")
STATE_USER = ("state_33", "pw")
NEIGHBOR_STATE_USER = ("state_32", "pw")
NATIONAL_USER = ("national_user", "pw")

OUT_JSON = Path("DISTRICT603_LIVE_CAMPAIGN_REPORT.json")
REPORT_KEY = "manual_off_priority_campaign_100"


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def login(username: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=25)
    r.raise_for_status()
    return r.json()["access_token"]


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_json(path: str, token: str, params: dict[str, Any] | None = None, timeout: int = 90) -> Any:
    r = requests.get(f"{BASE}{path}", headers=headers(token), params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def post_json(path: str, token: str, payload: dict[str, Any], timeout: int = 90) -> tuple[int, Any]:
    r = requests.post(f"{BASE}{path}", headers=headers(token), json=payload, timeout=timeout)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    return r.status_code, body


def wait_solver_completed(token: str, max_wait_s: int = 240) -> dict[str, Any]:
    started = time.time()
    last: dict[str, Any] = {}
    while time.time() - started < max_wait_s:
        try:
            last = get_json("/district/solver-status", token, timeout=45)
            status = str(last.get("status") or "").lower()
            if status in {"completed", "failed", "failed_reconciliation"}:
                return last
        except Exception as err:
            last = {"status": "poll_error", "detail": str(err)}
        time.sleep(2)
    return last


def _normalize_qty(meta: dict[str, Any], qty: float) -> float:
    max_reasonable = float(meta.get("max_reasonable_quantity") or meta.get("max_per_resource") or 1000.0)
    value = max(1.0, min(float(qty), max_reasonable))
    if bool(meta.get("requires_integer_quantity")) or str(meta.get("count_type") or "").lower() == "integer":
        value = float(int(value))
        if value < 1:
            value = 1.0
    return value


def _stock_row_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        rid = str(row.get("resource_id"))
        out[rid] = {
            "district": float(row.get("district_stock") or 0.0),
            "state": float(row.get("state_stock") or 0.0),
            "national": float(row.get("national_stock") or 0.0),
            "available": float(row.get("available_stock") or 0.0),
        }
    return out


def run_metrics(con: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    cur = con.cursor()

    cur.execute(
        "SELECT COALESCE(SUM(demand_quantity),0.0) FROM final_demands WHERE solver_run_id=?",
        (int(run_id),),
    )
    final_demand_total = float(cur.fetchone()[0] or 0.0)

    cur.execute(
        "SELECT COALESCE(SUM(allocated_quantity),0.0) FROM allocations WHERE solver_run_id=? AND is_unmet=0",
        (int(run_id),),
    )
    allocated_total = float(cur.fetchone()[0] or 0.0)

    cur.execute(
        "SELECT COALESCE(SUM(allocated_quantity),0.0) FROM allocations WHERE solver_run_id=? AND is_unmet=1",
        (int(run_id),),
    )
    unmet_total = float(cur.fetchone()[0] or 0.0)

    cur.execute(
        "SELECT status, COUNT(*) FROM requests WHERE run_id=? GROUP BY status",
        (int(run_id),),
    )
    req_status_counts = {str(k): int(v) for k, v in cur.fetchall()}

    total_out = allocated_total + unmet_total
    lineage_gap = abs(final_demand_total - total_out)

    return {
        "run_id": int(run_id),
        "final_demand_total": final_demand_total,
        "allocated_total": allocated_total,
        "unmet_total": unmet_total,
        "lineage_gap": lineage_gap,
        "lineage_balanced": bool(lineage_gap <= 1e-6),
        "allocation_ratio": (allocated_total / final_demand_total) if final_demand_total > 1e-9 else 0.0,
        "unmet_ratio": (unmet_total / final_demand_total) if final_demand_total > 1e-9 else 0.0,
        "request_status_counts": req_status_counts,
    }


VARIANTS = [
    {"name": "emergency_t0_critical", "time": 0, "priority": 5, "urgency": 5, "district_mult": 1.20, "state_mult": 0.75, "national_mult": 0.00, "extra": 8.0},
    {"name": "future_t4_high_claim", "time": 4, "priority": 5, "urgency": 4, "district_mult": 0.65, "state_mult": 0.70, "national_mult": 0.10, "extra": 6.0},
    {"name": "mid_t2_balanced", "time": 2, "priority": 4, "urgency": 4, "district_mult": 0.70, "state_mult": 0.45, "national_mult": 0.00, "extra": 5.0},
    {"name": "low_t1_noncritical", "time": 1, "priority": 2, "urgency": 2, "district_mult": 0.30, "state_mult": 0.20, "national_mult": 0.00, "extra": 3.0},
    {"name": "state_pressure", "time": 1, "priority": 4, "urgency": 5, "district_mult": 0.95, "state_mult": 1.20, "national_mult": 0.00, "extra": 10.0},
    {"name": "national_pressure", "time": 0, "priority": 5, "urgency": 5, "district_mult": 1.00, "state_mult": 1.00, "national_mult": 0.90, "extra": 20.0},
    {"name": "rankless_ml_candidate", "time": 0, "priority": None, "urgency": None, "district_mult": 0.80, "state_mult": 0.60, "national_mult": 0.10, "extra": 7.0},
    {"name": "deferred_t3_medium", "time": 3, "priority": 3, "urgency": 3, "district_mult": 0.65, "state_mult": 0.40, "national_mult": 0.00, "extra": 5.0},
    {"name": "low_stock_push", "time": 0, "priority": 5, "urgency": 5, "district_mult": 1.40, "state_mult": 1.30, "national_mult": 0.25, "extra": 15.0},
    {"name": "future_rebound", "time": 4, "priority": 4, "urgency": 5, "district_mult": 0.85, "state_mult": 0.80, "national_mult": 0.15, "extra": 12.0},
]


def build_case(
    *,
    run_index: int,
    resources: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    rng = random.Random(9000 + int(run_index))
    variant = VARIANTS[run_index % len(VARIANTS)]

    resource_meta = {str(r.get("resource_id")): r for r in resources if isinstance(r, dict)}
    candidates = [r for r in stock_rows if str(r.get("resource_id")) in resource_meta]
    candidates.sort(key=lambda x: (float(x.get("available_stock") or 0.0), str(x.get("resource_id"))))
    if not candidates:
        raise ValueError("No candidate stock rows available")

    # Intentionally choose low-available resources often to stress escalation and aid flow.
    pick_window = max(3, min(len(candidates), 12))
    chosen = candidates[rng.randrange(0, pick_window)]

    rid = str(chosen.get("resource_id"))
    meta = resource_meta[rid]

    district = float(chosen.get("district_stock") or 0.0)
    state = float(chosen.get("state_stock") or 0.0)
    national = float(chosen.get("national_stock") or 0.0)

    desired = (
        district * float(variant["district_mult"])
        + state * float(variant["state_mult"])
        + national * float(variant["national_mult"])
        + float(variant["extra"])
    )

    qty = _normalize_qty(meta, desired)

    return {
        "run_index": int(run_index),
        "variant": str(variant["name"]),
        "resource_id": rid,
        "resource_name": str(meta.get("resource_name") or meta.get("label") or rid),
        "class": str(meta.get("class") or ""),
        "time": int(variant["time"]),
        "quantity": float(qty),
        "priority": variant["priority"],
        "urgency": variant["urgency"],
        "pre_stock": {
            "district": district,
            "state": state,
            "national": national,
            "available": float(chosen.get("available_stock") or 0.0),
        },
    }


def append_report(block: dict[str, Any]) -> None:
    report = json.loads(OUT_JSON.read_text(encoding="utf-8")) if OUT_JSON.exists() else {}
    report[REPORT_KEY] = block
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def write_markdown(block: dict[str, Any], out_path: Path) -> None:
    summary = block.get("summary") or {}
    first_50 = summary.get("first_50") or {}
    lines = [
        "# Manual-Off Priority Campaign (100 Runs)",
        "",
        f"- Started: {block.get('started_at')}",
        f"- Ended: {block.get('ended_at')}",
        f"- API Base: {BASE}",
        "- Mode Policy: PRIORITY_URGENCY_INFLUENCE_MODE=off (manual-first decision path)",
        "",
        "## Overall Summary",
        f"- Total Runs: {summary.get('total_runs')}",
        f"- Solver Completed: {summary.get('solver_completed')}",
        f"- Requests Accepted: {summary.get('requests_accepted')}",
        f"- Manual Rank Effective Source Count: {summary.get('effective_source_human')}",
        f"- Predicted Rank Effective Source Count: {summary.get('effective_source_predicted')}",
        f"- Default Rank Effective Source Count: {summary.get('effective_source_default')}",
        f"- State Escalation Seen: {summary.get('state_escalations_seen')}",
        f"- National Escalation Seen: {summary.get('national_escalations_seen')}",
        f"- Neighbor Offers Attempted/OK: {summary.get('neighbor_offers_attempted')}/{summary.get('neighbor_offers_ok')}",
        f"- State Aid Attempted/OK: {summary.get('state_pool_aid_attempted')}/{summary.get('state_pool_aid_ok')}",
        f"- National Aid Attempted/OK: {summary.get('national_pool_aid_attempted')}/{summary.get('national_pool_aid_ok')}",
        f"- Claim Actions Attempted/OK: {summary.get('claim_actions_attempted')}/{summary.get('claim_actions_ok')}",
        f"- Demand-Allocation Lineage Balanced Runs: {summary.get('lineage_balanced_runs')}",
        f"- Avg Allocation Ratio: {summary.get('avg_allocation_ratio')}",
        f"- Avg Unmet Ratio: {summary.get('avg_unmet_ratio')}",
        "",
        "## First 50 Runs Focus",
        f"- Runs: {first_50.get('runs')}",
        f"- Solver Completed: {first_50.get('solver_completed')}",
        f"- State Escalations Seen: {first_50.get('state_escalations_seen')}",
        f"- National Escalations Seen: {first_50.get('national_escalations_seen')}",
        f"- Avg Allocation Ratio: {first_50.get('avg_allocation_ratio')}",
        f"- Avg Unmet Ratio: {first_50.get('avg_unmet_ratio')}",
        "",
        "## Variant Coverage",
    ]

    for row in block.get("variant_breakdown", []):
        lines.append(
            f"- {row.get('variant')}: runs={row.get('runs')} completed={row.get('completed')} "
            f"state_escalations={row.get('state_escalations')} national_escalations={row.get('national_escalations')}"
        )

    lines.extend([
        "",
        "## Notes on Optimality Under Constraints",
        "- Optimality is evaluated as solver-feasibility consistency: final_demand ~= allocated + unmet for each completed run.",
        "- High unmet in low-stock and emergency variants is expected behavior under finite district/state/national stock constraints.",
        "- State and national pool aid attempts validate that escalated demand can be serviced by higher-level pools when available.",
        "",
        "## Raw Detail",
        f"- Full per-run detail is in {OUT_JSON.name} under key `{REPORT_KEY}`.",
    ])

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--md", default="MANUAL_OFF_PRIORITY_CAMPAIGN_100_REPORT.md")
    args = parser.parse_args()

    district_token = login(*DISTRICT_USER)
    state_token = login(*STATE_USER)
    neighbor_token = login(*NEIGHBOR_STATE_USER)
    national_token = login(*NATIONAL_USER)

    resources = get_json("/metadata/resources", district_token)

    con = sqlite3.connect("backend.db")

    existing_block: dict[str, Any] | None = None
    if OUT_JSON.exists():
        try:
            report = json.loads(OUT_JSON.read_text(encoding="utf-8"))
            candidate = report.get(REPORT_KEY)
            if isinstance(candidate, dict):
                existing_block = candidate
        except Exception:
            existing_block = None

    if bool(args.resume) and isinstance(existing_block, dict):
        block = existing_block
        block.setdefault("started_at", now_iso())
        block.setdefault("runs", [])
        block.setdefault("config", {})
        block["status"] = "running"
        cfg = block.get("config") or {}
        prev_target = int((cfg.get("requested_runs") or 0) if isinstance(cfg, dict) else 0)
        target_runs = max(int(args.runs), prev_target, len(block.get("runs") or []))
        cfg["requested_runs"] = int(target_runs)
        cfg.setdefault("policy", {
            "priority_urgency_influence_mode": "off",
            "manual_entries_must_drive_effective_rank": True,
            "ml_shadow_allowed": True,
        })
        block["config"] = cfg
    else:
        target_runs = int(args.runs)
        block = {
            "started_at": now_iso(),
            "status": "running",
            "config": {
                "requested_runs": int(target_runs),
                "policy": {
                    "priority_urgency_influence_mode": "off",
                    "manual_entries_must_drive_effective_rank": True,
                    "ml_shadow_allowed": True,
                },
            },
            "runs": [],
        }

    if args.append:
        append_report(block)

    start_idx = len(block.get("runs") or [])

    for idx in range(start_idx, int(target_runs)):
        stock_rows = get_json("/district/stock", district_token)
        case = build_case(run_index=idx + 1, resources=resources, stock_rows=stock_rows)

        payload = {
            "resource_id": case["resource_id"],
            "time": int(case["time"]),
            "quantity": float(case["quantity"]),
            "priority": case["priority"],
            "urgency": case["urgency"],
            "confidence": 1.0,
            "source": "human",
        }

        req_status, req_body = post_json("/district/request", district_token, payload, timeout=60)

        try:
            run_trigger_status, run_trigger_body = post_json("/district/run", district_token, {}, timeout=300)
        except Exception as err:
            run_trigger_status, run_trigger_body = 599, {"detail": str(err)}

        solver_status = wait_solver_completed(district_token, max_wait_s=300)
        solver_run_id = int(solver_status.get("solver_run_id") or 0)
        run_db = run_metrics(con, solver_run_id) if solver_run_id > 0 else {}

        request_id = int(req_body.get("request_id") or 0) if isinstance(req_body, dict) else 0
        district_rows = get_json("/district/requests", district_token, params={"latest_only": True})
        district_row = next((r for r in district_rows if int(r.get("id") or 0) == request_id), None)

        state_escalations = get_json("/state/escalations", state_token)
        state_view = next((r for r in state_escalations if int(r.get("id") or 0) == request_id), None) if isinstance(state_escalations, list) else None

        national_escalations = get_json("/national/escalations", national_token)
        national_view = next((r for r in national_escalations if int(r.get("id") or 0) == request_id), None) if isinstance(national_escalations, list) else None

        neighbor_offer = None
        if state_view and ((idx + 1) % 3 == 0):
            market = get_json("/state/mutual-aid/market", neighbor_token)
            market_row = next((r for r in market if int(r.get("id") or 0) == request_id), None) if isinstance(market, list) else None
            if market_row is not None:
                remaining = float(market_row.get("remaining_quantity") or 0.0)
                if remaining > 0:
                    qty_offer = max(1.0, round(min(remaining, 0.5 * remaining), 2))
                    off_status, off_body = post_json(
                        "/state/mutual-aid/offers",
                        neighbor_token,
                        {
                            "request_id": int(request_id),
                            "quantity_offered": qty_offer,
                        },
                        timeout=60,
                    )
                    neighbor_offer = {
                        "status": off_status,
                        "body": off_body,
                        "quantity_offered": qty_offer,
                    }

        state_aid = None
        if state_view and ((idx + 1) % 7 == 0):
            aid_status, aid_body = post_json(
                "/state/pool/allocate",
                state_token,
                {
                    "resource_id": case["resource_id"],
                    "time": int(case["time"]),
                    "quantity": 1.0,
                    "target_district": "district_603",
                    "note": f"campaign_state_aid_run_{idx + 1}",
                },
                timeout=60,
            )
            state_aid = {"status": aid_status, "body": aid_body}

        national_aid = None
        if national_view and ((idx + 1) % 5 == 0):
            n_status, n_body = post_json(
                "/national/pool/allocate",
                national_token,
                {
                    "state_code": "33",
                    "resource_id": case["resource_id"],
                    "time": int(case["time"]),
                    "quantity": 1.0,
                    "target_district": "district_603",
                    "note": f"campaign_national_aid_run_{idx + 1}",
                },
                timeout=60,
            )
            national_aid = {"status": n_status, "body": n_body}

        claim_action = None
        if ((idx + 1) % 10 == 0):
            alloc_rows = get_json("/district/allocations", district_token)
            pick = next(
                (
                    r for r in alloc_rows
                    if str(r.get("resource_id")) == str(case["resource_id"])
                    and int(r.get("time") or -1) == int(case["time"])
                    and float(r.get("allocated_quantity") or 0.0) >= 1.0
                    and str(r.get("status") or "").lower() == "allocated"
                ),
                None,
            )
            if pick is not None:
                c_status, c_body = post_json(
                    "/district/claim",
                    district_token,
                    {
                        "resource_id": case["resource_id"],
                        "time": int(case["time"]),
                        "quantity": 1.0,
                        "claimed_by": "campaign",
                        "solver_run_id": int(pick.get("solver_run_id") or 0),
                    },
                    timeout=60,
                )
                claim_action = {"claim_status": c_status, "claim_body": c_body}

        run_row = {
            "run_number": idx + 1,
            "case": case,
            "request": {
                "status": req_status,
                "body": req_body,
                "payload": payload,
            },
            "run_trigger": {
                "status": run_trigger_status,
                "body": run_trigger_body,
            },
            "solver_status": solver_status,
            "run_db": run_db,
            "district_view": district_row,
            "state_view": state_view,
            "national_view": national_view,
            "neighbor_offer": neighbor_offer,
            "state_pool_aid": state_aid,
            "national_pool_aid": national_aid,
            "claim_action": claim_action,
            "checks": {
                "request_accepted": req_status in {200, 201},
                "solver_completed": str(solver_status.get("status") or "").lower() == "completed",
                "lineage_balanced": bool((run_db or {}).get("lineage_balanced", False)),
                "manual_rank_used_when_provided": (
                    True
                    if district_row is None
                    else (
                        district_row.get("effective_priority_source") == "human" and district_row.get("effective_urgency_source") == "human"
                    ) if (case.get("priority") is not None and case.get("urgency") is not None) else True
                ),
            },
        }

        block["runs"].append(run_row)

        if args.append:
            block["last_saved_at"] = now_iso()
            block["progress"] = {
                "runs_recorded": len(block["runs"]),
                "requested_runs": int(target_runs),
            }
            append_report(block)

    con.close()

    runs = block["runs"]
    completed = [r for r in runs if r.get("checks", {}).get("solver_completed")]

    def _avg(items: list[float]) -> float:
        return float(sum(items) / len(items)) if items else 0.0

    lineage_balanced_runs = sum(1 for r in runs if bool(r.get("checks", {}).get("lineage_balanced")))
    requests_accepted = sum(1 for r in runs if bool(r.get("checks", {}).get("request_accepted")))

    state_escalations_seen = sum(1 for r in runs if isinstance(r.get("state_view"), dict))
    national_escalations_seen = sum(1 for r in runs if isinstance(r.get("national_view"), dict))

    source_human = sum(1 for r in runs if isinstance(r.get("district_view"), dict) and r["district_view"].get("effective_priority_source") == "human")
    source_pred = sum(1 for r in runs if isinstance(r.get("district_view"), dict) and r["district_view"].get("effective_priority_source") == "predicted")
    source_default = sum(1 for r in runs if isinstance(r.get("district_view"), dict) and r["district_view"].get("effective_priority_source") == "default")

    neighbor_offers_attempted = sum(1 for r in runs if isinstance(r.get("neighbor_offer"), dict))
    neighbor_offers_ok = sum(1 for r in runs if isinstance(r.get("neighbor_offer"), dict) and int((r.get("neighbor_offer") or {}).get("status") or 0) == 200)

    state_pool_aid_attempted = sum(1 for r in runs if isinstance(r.get("state_pool_aid"), dict))
    state_pool_aid_ok = sum(1 for r in runs if isinstance(r.get("state_pool_aid"), dict) and int((r.get("state_pool_aid") or {}).get("status") or 0) == 200)

    national_pool_aid_attempted = sum(1 for r in runs if isinstance(r.get("national_pool_aid"), dict))
    national_pool_aid_ok = sum(1 for r in runs if isinstance(r.get("national_pool_aid"), dict) and int((r.get("national_pool_aid") or {}).get("status") or 0) == 200)

    claim_actions_attempted = sum(1 for r in runs if isinstance(r.get("claim_action"), dict))
    claim_actions_ok = sum(1 for r in runs if isinstance(r.get("claim_action"), dict) and int((r.get("claim_action") or {}).get("claim_status") or 0) == 200)

    alloc_ratios = [float((r.get("run_db") or {}).get("allocation_ratio") or 0.0) for r in completed]
    unmet_ratios = [float((r.get("run_db") or {}).get("unmet_ratio") or 0.0) for r in completed]

    first_50_rows = runs[:50]
    first_50_completed = [r for r in first_50_rows if bool(r.get("checks", {}).get("solver_completed"))]
    first_50_alloc = [float((r.get("run_db") or {}).get("allocation_ratio") or 0.0) for r in first_50_completed]
    first_50_unmet = [float((r.get("run_db") or {}).get("unmet_ratio") or 0.0) for r in first_50_completed]

    variants: dict[str, dict[str, Any]] = {}
    for row in runs:
        v = str((row.get("case") or {}).get("variant") or "unknown")
        bucket = variants.setdefault(v, {"variant": v, "runs": 0, "completed": 0, "state_escalations": 0, "national_escalations": 0})
        bucket["runs"] += 1
        if bool(row.get("checks", {}).get("solver_completed")):
            bucket["completed"] += 1
        if isinstance(row.get("state_view"), dict):
            bucket["state_escalations"] += 1
        if isinstance(row.get("national_view"), dict):
            bucket["national_escalations"] += 1

    block["variant_breakdown"] = sorted(variants.values(), key=lambda x: x["variant"])

    block["summary"] = {
        "total_runs": len(runs),
        "solver_completed": len(completed),
        "requests_accepted": requests_accepted,
        "lineage_balanced_runs": lineage_balanced_runs,
        "avg_allocation_ratio": round(_avg(alloc_ratios), 6),
        "avg_unmet_ratio": round(_avg(unmet_ratios), 6),
        "state_escalations_seen": state_escalations_seen,
        "national_escalations_seen": national_escalations_seen,
        "effective_source_human": source_human,
        "effective_source_predicted": source_pred,
        "effective_source_default": source_default,
        "neighbor_offers_attempted": neighbor_offers_attempted,
        "neighbor_offers_ok": neighbor_offers_ok,
        "state_pool_aid_attempted": state_pool_aid_attempted,
        "state_pool_aid_ok": state_pool_aid_ok,
        "national_pool_aid_attempted": national_pool_aid_attempted,
        "national_pool_aid_ok": national_pool_aid_ok,
        "claim_actions_attempted": claim_actions_attempted,
        "claim_actions_ok": claim_actions_ok,
        "first_50": {
            "runs": len(first_50_rows),
            "solver_completed": len(first_50_completed),
            "state_escalations_seen": sum(1 for r in first_50_rows if isinstance(r.get("state_view"), dict)),
            "national_escalations_seen": sum(1 for r in first_50_rows if isinstance(r.get("national_view"), dict)),
            "avg_allocation_ratio": round(_avg(first_50_alloc), 6),
            "avg_unmet_ratio": round(_avg(first_50_unmet), 6),
        },
    }

    block["ended_at"] = now_iso()
    block["status"] = "completed"
    block["progress"] = {
        "runs_recorded": len(block["runs"]),
        "requested_runs": int(target_runs),
    }

    if args.append:
        append_report(block)

    md_path = Path(str(args.md))
    write_markdown(block, md_path)

    print(json.dumps(block["summary"], indent=2))
    print(json.dumps({"report_key": REPORT_KEY, "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
