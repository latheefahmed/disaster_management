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


def wait_solver_completed(token: str, max_wait_s: int = 240) -> dict[str, Any]:
    started = time.time()
    last: dict[str, Any] = {}
    while time.time() - started < max_wait_s:
        last = get_json("/district/solver-status", token)
        status = str(last.get("status") or "").lower()
        if status in {"completed", "failed", "failed_reconciliation"}:
            return last
        time.sleep(2)
    return last


def _normalize_qty(resource_meta: dict[str, Any], qty: float) -> float:
    max_reasonable = float(
        resource_meta.get("max_reasonable_quantity")
        or resource_meta.get("max_per_resource")
        or 1_000_000
    )
    qty = max(1.0, min(float(qty), max_reasonable))
    if bool(resource_meta.get("requires_integer_quantity")) or str(resource_meta.get("count_type") or "").lower() == "integer":
        qty = float(int(qty))
        if qty < 1:
            qty = 1.0
    return qty


def choose_variants(
    stock_rows: list[dict[str, Any]],
    resource_meta_map: dict[str, dict[str, Any]],
    total_cases: int = 10,
) -> list[dict[str, Any]]:
    rows = [
        r for r in stock_rows
        if float(r.get("available_stock") or 0.0) > 0
        and str(r.get("resource_id")) in resource_meta_map
    ]
    rows.sort(key=lambda r: float(r.get("district_stock") or 0.0) + float(r.get("state_stock") or 0.0))
    if not rows:
        return []

    picks: list[dict[str, Any]] = []
    for idx in range(total_cases):
        row = rows[idx % len(rows)]
        rid = str(row.get("resource_id"))
        meta = resource_meta_map.get(rid, {})
        district = float(row.get("district_stock") or 0.0)
        state = float(row.get("state_stock") or 0.0)
        national = float(row.get("national_stock") or 0.0)
        available = float(row.get("available_stock") or 0.0)
        max_reasonable = float(meta.get("max_reasonable_quantity") or meta.get("max_per_resource") or 1_000_000)
        t = idx % 5

        if idx == 0:
            desired = max(district + 1.0, 1.0)
            if state > 0:
                desired = min(desired, district + max(1.0, state * 0.5))
            qty = _normalize_qty(meta, desired)
            variant = "state_can_cover_district_shortfall"
            if not (qty > district and qty <= (district + state + 1e-9)):
                qty = _normalize_qty(meta, max(1.0, min(max_reasonable, district * 0.5 + 1.0)))
                variant = "fallback_within_resource_limits"
        elif idx in {1, 2, 3, 4, 8, 9}:
            desired = district + state + max(10.0, (0.10 * max(available, 1.0)))
            if max_reasonable <= district + state:
                desired = max_reasonable
                variant = "max_cap_pressure_cannot_exceed_state_total"
            else:
                variant = "district_state_shortage_immediate"
            qty = _normalize_qty(meta, desired)
        elif idx in {5, 6, 7}:
            desired = district + state + national + 1000.0
            if max_reasonable <= district + state + national:
                desired = max_reasonable
                variant = "time_series_preservation_pressure"
            else:
                variant = "all_levels_shortage_national_pressure"
            qty = _normalize_qty(meta, desired)
        else:
            qty = _normalize_qty(meta, max(1.0, min(max_reasonable, district + state + 100.0)))
            variant = "district_state_shortage_immediate"

        picks.append(
            {
                "case_id": idx + 1,
                "resource_id": rid,
                "time": int(t),
                "district_stock": district,
                "state_stock": state,
                "national_stock": national,
                "available_stock": available,
                "requested_quantity": round(float(qty), 2),
                "variant": variant,
            }
        )
    return picks


def main() -> None:
    district_token = login(*DISTRICT_USER)
    state_token = login(*STATE_USER)
    neighbor_token = login(*NEIGHBOR_STATE_USER)

    if OUT_JSON.exists():
        report = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    else:
        report = {}

    stock_rows = get_json("/district/stock", district_token)
    resources = get_json("/metadata/resources", district_token)
    resource_meta_map = {str(r.get("resource_id")): r for r in resources if isinstance(r, dict)}
    cases = choose_variants(stock_rows, resource_meta_map=resource_meta_map, total_cases=10)

    append_block: dict[str, Any] = {
        "started_at": now_iso(),
        "policy": {
            "direct_state_escalation_endpoint_called": False,
            "state_escalation_endpoint": "/state/escalations/{request_id}",
            "agent_manual_actions_allowed": ["mutual_aid_offer_from_neighbor_state"],
            "notes": "Campaign intentionally avoids direct state escalation call; only neighbor-state manual aid offers are made by agent.",
        },
        "cases": [],
        "run": {},
        "manual_aid_offers": [],
        "manual_escalations_by_agent": [],
    }

    created_request_ids: list[int] = []

    for case in cases:
        payload = {
            "resource_id": case["resource_id"],
            "time": int(case["time"]),
            "quantity": float(case["requested_quantity"]),
            "priority": 5,
            "urgency": 5,
            "confidence": 1.0,
            "source": "human",
        }
        req_status, req_body = post_json("/district/request", district_token, payload, timeout=40)
        request_id = int(req_body.get("request_id") or 0) if isinstance(req_body, dict) else 0
        if request_id > 0:
            created_request_ids.append(request_id)

        append_block["cases"].append(
            {
                **case,
                "request_status": req_status,
                "request_body": req_body,
                "request_id": request_id,
            }
        )

    try:
        trigger_status, trigger_body = post_json("/district/run", district_token, {}, timeout=300)
    except Exception as e:
        trigger_status, trigger_body = 599, {"detail": f"run trigger timeout/error: {e}"}

    append_block["run"] = {
        "trigger_status": trigger_status,
        "trigger_body": trigger_body,
        "solver_status": wait_solver_completed(district_token),
    }

    state_candidates = get_json("/state/escalations", state_token)
    by_id = {}
    if isinstance(state_candidates, list):
        by_id = {int(row.get("id") or 0): row for row in state_candidates}

    for c in append_block["cases"]:
        req_id = int(c.get("request_id") or 0)
        c["state_view"] = by_id.get(req_id)

        req_qty = float(c.get("requested_quantity") or 0.0)
        unmet_qty = None
        if isinstance(c["state_view"], dict):
            unmet_qty = float(c["state_view"].get("unmet_quantity") or 0.0)
        aid_qty = max(1.0, round((unmet_qty if unmet_qty and unmet_qty > 0 else req_qty) * 0.35, 2))

        m_req_status, m_req_body = post_json(
            "/district/mutual-aid/request",
            district_token,
            {
                "resource_id": c["resource_id"],
                "quantity_requested": aid_qty,
                "time": int(c["time"]),
            },
            timeout=40,
        )

        aid_entry: dict[str, Any] = {
            "base_request_id": req_id,
            "resource_id": c["resource_id"],
            "time": int(c["time"]),
            "mutual_aid_request": {"status": m_req_status, "body": m_req_body},
            "offer": {"status": "SKIP", "body": "No eligible market row"},
        }

        if m_req_status == 200 and isinstance(m_req_body, dict):
            aid_request_id = int(m_req_body.get("request_id") or 0)
            market = get_json("/state/mutual-aid/market", neighbor_token)
            chosen = None
            if isinstance(market, list):
                for row in market:
                    if int(row.get("id") or 0) == aid_request_id:
                        chosen = row
                        break
                if chosen is None:
                    for row in market:
                        if str(row.get("requesting_state")) == "33" and str(row.get("resource_id")) == str(c["resource_id"]):
                            chosen = row
                            break

            if chosen is not None:
                offered_qty = max(1.0, round(min(aid_qty, float(chosen.get("quantity_requested") or aid_qty)), 2))
                off_status, off_body = post_json(
                    "/state/mutual-aid/offers",
                    neighbor_token,
                    {
                        "request_id": int(chosen.get("id")),
                        "quantity_offered": offered_qty,
                    },
                    timeout=40,
                )
                aid_entry["offer"] = {"status": off_status, "body": off_body}

                append_block["manual_escalations_by_agent"].append(
                    {
                        "kind": "mutual_aid_offer_from_neighbor_state",
                        "request_id": int(chosen.get("id") or 0),
                        "offering_state": "32",
                        "requesting_state": "33",
                        "resource_id": c["resource_id"],
                        "quantity_offered": offered_qty,
                        "status": off_status,
                    }
                )

        append_block["manual_aid_offers"].append(aid_entry)

    append_block["summary"] = {
        "ended_at": now_iso(),
        "cases_total": len(append_block["cases"]),
        "district_requests_accepted": sum(1 for c in append_block["cases"] if int(c.get("request_status") or 0) in {200, 201}),
        "mutual_aid_requests_accepted": sum(1 for x in append_block["manual_aid_offers"] if int((x.get("mutual_aid_request") or {}).get("status") or 0) == 200),
        "manual_neighbor_offers_ok": sum(1 for x in append_block["manual_aid_offers"] if int((x.get("offer") or {}).get("status") or 0) == 200),
        "state_escalation_endpoint_called": False,
    }

    report["manual_escalation_append"] = append_block
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(json.dumps(append_block["summary"], indent=2))
    print(f"appended_to={OUT_JSON}")


if __name__ == "__main__":
    main()
