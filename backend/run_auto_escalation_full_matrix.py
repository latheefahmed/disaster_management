from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

BASE = "http://127.0.0.1:8000"
DISTRICT_USER = ("district_603", "pw")
STATE_USER = ("state_33", "pw")
NEIGHBOR_STATE_USER = ("state_32", "pw")

OUT_JSON = Path("DISTRICT603_LIVE_CAMPAIGN_REPORT.json")
TOTAL_CASES = 24
WAVE_SIZE = 8


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def login(username: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_json(path: str, token: str, params: dict[str, Any] | None = None, timeout: int = 60) -> Any:
    r = requests.get(f"{BASE}{path}", headers=headers(token), params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def post_json(path: str, token: str, payload: dict[str, Any], timeout: int = 60) -> tuple[int, Any]:
    r = requests.post(f"{BASE}{path}", headers=headers(token), json=payload, timeout=timeout)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    return r.status_code, body


def wait_solver_completed(token: str, max_wait_s: int = 300) -> dict[str, Any]:
    started = time.time()
    last: dict[str, Any] = {}
    while time.time() - started < max_wait_s:
        last = get_json("/district/solver-status", token)
        status = str(last.get("status") or "").lower()
        if status in {"completed", "failed", "failed_reconciliation"}:
            return last
        time.sleep(2)
    return last


def stock_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
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


def _normalize_qty(meta: dict[str, Any], qty: float) -> float:
    max_reasonable = float(meta.get("max_reasonable_quantity") or meta.get("max_per_resource") or 1_000_000)
    qty = max(1.0, min(float(qty), max_reasonable))
    if bool(meta.get("requires_integer_quantity")) or str(meta.get("count_type") or "").lower() == "integer":
        qty = float(int(qty))
        if qty < 1:
            qty = 1.0
    return qty


def build_cases(stock_rows: list[dict[str, Any]], resources: list[dict[str, Any]], total_cases: int = TOTAL_CASES) -> list[dict[str, Any]]:
    meta_map = {str(r.get("resource_id")): r for r in resources if isinstance(r, dict)}
    rows = [
        row for row in stock_rows
        if str(row.get("resource_id")) in meta_map and float(row.get("available_stock") or 0.0) > 0
    ]

    rows.sort(key=lambda x: (float(x.get("district_stock") or 0.0) + float(x.get("state_stock") or 0.0), float(x.get("national_stock") or 0.0)))
    if not rows:
        return []

    variants = [
        "district_short_state_cover",
        "district_state_short_neighbor_market",
        "district_state_short_neighbor_market",
        "immediate_high_urgency",
        "time_series_day1_pressure",
        "time_series_day2_pressure",
        "all_level_short_national_push",
        "all_level_short_national_push",
    ]

    cases: list[dict[str, Any]] = []
    for idx in range(total_cases):
        row = rows[idx % len(rows)]
        rid = str(row.get("resource_id"))
        meta = meta_map[rid]
        district = float(row.get("district_stock") or 0.0)
        state = float(row.get("state_stock") or 0.0)
        national = float(row.get("national_stock") or 0.0)
        available = float(row.get("available_stock") or 0.0)
        variant = variants[idx % len(variants)]
        t = idx % 5

        if variant == "district_short_state_cover":
            desired = district + max(1.0, min(state * 0.6, 1000.0))
            priority, urgency = 4, 4
        elif variant in {"district_state_short_neighbor_market", "immediate_high_urgency"}:
            desired = district + state + max(10.0, 0.1 * max(available, 1.0))
            priority, urgency = (5, 5) if variant == "immediate_high_urgency" else (4, 5)
            if variant == "immediate_high_urgency":
                t = 0
        elif variant in {"time_series_day1_pressure", "time_series_day2_pressure"}:
            desired = district + state + max(20.0, 0.07 * max(available, 1.0))
            priority, urgency = 4, 4
            t = 1 if variant == "time_series_day1_pressure" else 2
        else:
            desired = district + state + national + max(50.0, 0.05 * max(available, 1.0))
            priority, urgency = 5, 5

        qty = _normalize_qty(meta, desired)
        cases.append(
            {
                "case_id": idx + 1,
                "resource_id": rid,
                "resource_name": str(meta.get("resource_name") or meta.get("label") or rid),
                "class": str(meta.get("class") or ""),
                "time": int(t),
                "variant": variant,
                "requested_quantity": float(qty),
                "priority": int(priority),
                "urgency": int(urgency),
                "pre_stock": {
                    "district": district,
                    "state": state,
                    "national": national,
                    "available": available,
                },
            }
        )
    return cases


def main() -> None:
    district_token = login(*DISTRICT_USER)
    state_token = login(*STATE_USER)
    neighbor_token = login(*NEIGHBOR_STATE_USER)
    national_token = login("national_user", "pw")

    report = json.loads(OUT_JSON.read_text(encoding="utf-8")) if OUT_JSON.exists() else {}

    resources = get_json("/metadata/resources", district_token)
    stock_rows = get_json("/district/stock", district_token)
    stock_before = stock_map(stock_rows)

    cases = build_cases(stock_rows, resources, total_cases=TOTAL_CASES)

    block: dict[str, Any] = {
        "started_at": now_iso(),
        "policy": {
            "target": "fully_auto_district_state_neighbor_national",
            "manual_actions_by_agent_allowed": ["neighbor_state_offer_only"],
            "state_escalation_endpoint_called": False,
            "state_offer_accept_called": False,
        },
        "requests": [],
        "waves": [],
        "manual_neighbor_offers": [],
        "consume_return_checks": [],
    }

    for case in cases:
        status, body = post_json(
            "/district/request",
            district_token,
            {
                "resource_id": case["resource_id"],
                "time": int(case["time"]),
                "quantity": float(case["requested_quantity"]),
                "priority": int(case["priority"]),
                "urgency": int(case["urgency"]),
                "confidence": 1.0,
                "source": "human",
            },
            timeout=40,
        )
        block["requests"].append(
            {
                **case,
                "request_status": status,
                "request_body": body,
                "request_id": int(body.get("request_id") or 0) if isinstance(body, dict) else 0,
            }
        )

    accepted_requests = [r for r in block["requests"] if int(r.get("request_status") or 0) in {200, 201}]

    for wave_start in range(0, len(accepted_requests), WAVE_SIZE):
        wave = accepted_requests[wave_start:wave_start + WAVE_SIZE]
        if not wave:
            continue

        try:
            trigger_status, trigger_body = post_json("/district/run", district_token, {}, timeout=300)
        except Exception as e:
            trigger_status, trigger_body = 599, {"detail": f"run trigger timeout/error: {e}"}

        solver_status = wait_solver_completed(district_token, max_wait_s=300)

        state_escalations = get_json("/state/escalations", state_token)
        esc_map = {int(row.get("id") or 0): row for row in state_escalations} if isinstance(state_escalations, list) else {}

        wave_request_ids = {int(item.get("request_id") or 0) for item in wave}
        wave_rows = []
        for item in wave:
            rid = int(item.get("request_id") or 0)
            wave_rows.append(
                {
                    "case_id": int(item["case_id"]),
                    "request_id": rid,
                    "resource_id": item["resource_id"],
                    "time": int(item["time"]),
                    "variant": item["variant"],
                    "state_view": esc_map.get(rid),
                }
            )

        market = get_json("/state/mutual-aid/market", neighbor_token)
        national_escalations = get_json("/national/escalations", national_token)
        national_map = {
            int(row.get("id") or 0): row
            for row in (national_escalations if isinstance(national_escalations, list) else [])
        }
        offers_this_wave: list[dict[str, Any]] = []
        wave_resource_time = {(str(x.get("resource_id")), int(x.get("time") or 0)) for x in wave}
        if isinstance(market, list):
            offered_market_ids: set[int] = set()
            for row in market:
                if str(row.get("requesting_state")) != "33":
                    continue
                if (str(row.get("resource_id")), int(row.get("time") or 0)) not in wave_resource_time:
                    continue
                req_id = int(row.get("id") or 0)
                if req_id in offered_market_ids:
                    continue
                remaining = float(row.get("remaining_quantity") or 0.0)
                if remaining <= 1e-9:
                    continue

                qty = max(1.0, round(min(remaining, remaining * 0.6), 2))
                off_status, off_body = post_json(
                    "/state/mutual-aid/offers",
                    neighbor_token,
                    {
                        "request_id": req_id,
                        "quantity_offered": qty,
                    },
                    timeout=40,
                )
                offer_entry = {
                    "market_request_id": req_id,
                    "resource_id": str(row.get("resource_id")),
                    "time": int(row.get("time") or 0),
                    "remaining_quantity": remaining,
                    "quantity_offered": qty,
                    "offer_status": off_status,
                    "offer_body": off_body,
                }
                offers_this_wave.append(offer_entry)
                block["manual_neighbor_offers"].append(offer_entry)
                offered_market_ids.add(req_id)

        block["waves"].append(
            {
                "wave_number": int(wave_start // WAVE_SIZE) + 1,
                "request_ids": sorted([int(x.get("request_id") or 0) for x in wave]),
                "run_trigger_status": trigger_status,
                "run_trigger_body": trigger_body,
                "solver_status": solver_status,
                "cases": wave_rows,
                "offers": offers_this_wave,
                "national_escalations": [
                    {
                        "request_id": int(c.get("request_id") or 0),
                        "national_view": national_map.get(int(c.get("request_id") or 0)),
                    }
                    for c in wave_rows
                ],
            }
        )

    # Claim/consume/return validations from latest allocated rows
    allocations = get_json("/district/allocations", district_token)
    allocations = [
        row for row in allocations
        if str(row.get("status") or "").lower() == "allocated"
        and float(row.get("allocated_quantity") or 0.0) > 0
    ]
    allocations.sort(key=lambda x: (-int(x.get("solver_run_id") or 0), int(x.get("time") or 0), int(x.get("id") or 0)))

    resource_map = {str(r.get("resource_id")): r for r in resources if isinstance(r, dict)}
    selected = allocations[:12]

    for idx, row in enumerate(selected, start=1):
        rid = str(row.get("resource_id"))
        t = int(row.get("time") or 0)
        run_id = int(row.get("solver_run_id") or 0)
        allocated = float(row.get("allocated_quantity") or 0.0)
        qty = max(1, min(int(allocated), 5))
        meta = resource_map.get(rid, {})
        cls = str(meta.get("class") or "")
        consumable = cls == "consumable" or bool(meta.get("is_consumable"))

        pre_stock_rows = get_json("/district/stock", district_token)
        pre_map = stock_map(pre_stock_rows)
        pre = pre_map.get(rid, {"district": 0.0, "state": 0.0, "national": 0.0, "available": 0.0})

        c_status, c_body = post_json(
            "/district/claim",
            district_token,
            {
                "resource_id": rid,
                "time": t,
                "quantity": qty,
                "claimed_by": "auto_matrix",
                "solver_run_id": run_id,
            },
            timeout=40,
        )

        action_status = "SKIP"
        action_body: Any = "SKIP"
        if c_status == 200:
            if consumable:
                action_status, action_body = post_json(
                    "/district/consume",
                    district_token,
                    {
                        "resource_id": rid,
                        "time": t,
                        "quantity": qty,
                        "solver_run_id": run_id,
                    },
                    timeout=40,
                )
            else:
                action_status, action_body = post_json(
                    "/district/return",
                    district_token,
                    {
                        "resource_id": rid,
                        "time": t,
                        "quantity": qty,
                        "reason": "manual",
                        "solver_run_id": run_id,
                        "allocation_source_scope": str(row.get("allocation_source_scope") or row.get("supply_level") or ""),
                        "allocation_source_code": str(row.get("allocation_source_code") or row.get("origin_state_code") or row.get("state_code") or ""),
                    },
                    timeout=40,
                )

        post_stock_rows = get_json("/district/stock", district_token)
        post_map = stock_map(post_stock_rows)
        post = post_map.get(rid, {"district": 0.0, "state": 0.0, "national": 0.0, "available": 0.0})

        pool_check = True
        if consumable and action_status == 200:
            pool_check = float(post["available"]) <= float(pre["available"]) + 1e-9
        if (not consumable) and action_status == 200:
            pool_check = float(post["available"]) >= float(pre["available"]) - 1e-9

        block["consume_return_checks"].append(
            {
                "check_id": idx,
                "resource_id": rid,
                "class": cls,
                "time": t,
                "solver_run_id": run_id,
                "attempt_qty": qty,
                "claim_status": c_status,
                "action": "consume" if consumable else "return",
                "action_status": action_status,
                "pre": pre,
                "post": post,
                "pool_update_check": bool(pool_check),
                "claim_body": c_body,
                "action_body": action_body,
            }
        )

    stock_after = stock_map(get_json("/district/stock", district_token))

    request_ok = sum(1 for r in block["requests"] if int(r.get("request_status") or 0) in {200, 201})
    wave_runs_completed = sum(1 for w in block["waves"] if str((w.get("solver_status") or {}).get("status", "")).lower() == "completed")
    offers_ok = sum(1 for o in block["manual_neighbor_offers"] if int(o.get("offer_status") or 0) == 200)
    claim_ok = sum(1 for c in block["consume_return_checks"] if int(c.get("claim_status") or 0) == 200)
    action_ok = sum(1 for c in block["consume_return_checks"] if int(c.get("action_status") or 0) == 200)
    pool_ok = sum(1 for c in block["consume_return_checks"] if bool(c.get("pool_update_check")))
    national_auto = 0
    for wave in block["waves"]:
        for row in wave.get("national_escalations", []):
            view = row.get("national_view") if isinstance(row, dict) else None
            if isinstance(view, dict) and str(view.get("status") or "").lower() == "escalated_national":
                national_auto += 1

    block["summary"] = {
        "ended_at": now_iso(),
        "cases_total": len(block["requests"]),
        "requests_accepted": request_ok,
        "waves_total": len(block["waves"]),
        "waves_solver_completed": wave_runs_completed,
        "manual_neighbor_offers_total": len(block["manual_neighbor_offers"]),
        "manual_neighbor_offers_ok": offers_ok,
        "auto_national_escalations_seen": national_auto,
        "consume_return_checks_total": len(block["consume_return_checks"]),
        "claims_ok": claim_ok,
        "actions_ok": action_ok,
        "pool_update_checks_ok": pool_ok,
        "state_escalation_endpoint_called": False,
        "state_offer_accept_called": False,
        "stock_snapshot_before_resources": len(stock_before),
        "stock_snapshot_after_resources": len(stock_after),
    }

    report["auto_escalation_full_matrix"] = block
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(json.dumps(block["summary"], indent=2))
    print(f"appended_to={OUT_JSON}")


if __name__ == "__main__":
    main()
