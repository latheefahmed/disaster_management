from __future__ import annotations

import json
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import requests

BASE = "http://127.0.0.1:8000"
OUT_JSON = Path("LIVE_AUTO_ESCALATION_30_QUANTITY_ONLY_REPORT.json")
OUT_MD = Path("LIVE_AUTO_ESCALATION_30_QUANTITY_ONLY_REPORT.md")
TOTAL_CASES = 30
WAVE_SIZE = 10


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def login_with_fallback(username: str, candidates: list[str]) -> str:
    last_err = None
    for pw in candidates:
        try:
            r = requests.post(f"{BASE}/auth/login", json={"username": username, "password": pw}, timeout=25)
            r.raise_for_status()
            return r.json()["access_token"]
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f"login failed for {username}: {last_err}")


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_json(path: str, token: str, params: dict[str, Any] | None = None, timeout: int = 60) -> Any:
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


def wait_for_run_completion(token: str, expected_run_id: int, max_wait_s: int = 360) -> dict[str, Any]:
    started = time.time()
    last: dict[str, Any] = {}
    while time.time() - started < max_wait_s:
        runs = get_json("/district/run-history", token)
        if isinstance(runs, list):
            row = next((r for r in runs if int(r.get("run_id") or 0) == int(expected_run_id)), None)
            if row:
                status = str(row.get("status") or "").lower()
                last = row
                if status in {"completed", "failed", "failed_reconciliation"}:
                    return row
        time.sleep(2)
    return last


def normalize_qty(meta: dict[str, Any], qty: float) -> float:
    max_reasonable = float(meta.get("max_reasonable_quantity") or meta.get("max_per_resource") or 1_000_000)
    qty = max(2.0, min(float(qty), max_reasonable))
    if bool(meta.get("requires_integer_quantity")) or str(meta.get("count_type") or "").lower() == "integer":
        qty = float(int(qty))
        if qty < 2:
            qty = 2.0
    return qty


def build_cases(stock_rows: list[dict[str, Any]], resources: list[dict[str, Any]], total_cases: int) -> list[dict[str, Any]]:
    meta_map = {str(r.get("resource_id")): r for r in resources if isinstance(r, dict)}
    rows = [
        row for row in stock_rows
        if str(row.get("resource_id")) in meta_map and float(row.get("available_stock") or 0.0) > 0
    ]
    rows.sort(key=lambda x: (float(x.get("district_stock") or 0.0), float(x.get("state_stock") or 0.0), float(x.get("national_stock") or 0.0)))
    if not rows:
        return []

    variants = [
        "district_preferred",
        "state_pressure",
        "neighbor_pressure",
        "national_pressure",
        "mixed_pressure",
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
        t = idx % 4

        if variant == "district_preferred":
            desired = max(2.0, min(district * 0.5, district if district > 0 else 2.0))
            priority, urgency = 3, 3
        elif variant == "state_pressure":
            desired = district + max(2.0, min(state * 0.4, 500.0))
            priority, urgency = 4, 4
        elif variant == "neighbor_pressure":
            desired = district + state + max(5.0, 0.03 * max(available, 1.0))
            priority, urgency = 4, 5
        elif variant == "national_pressure":
            desired = district + state + national + max(20.0, 0.02 * max(available, 1.0))
            priority, urgency = 5, 5
        else:
            desired = district + state + max(10.0, 0.05 * max(available, 1.0))
            priority, urgency = 4, 5

        qty = normalize_qty(meta, desired)

        cases.append(
            {
                "case_id": idx + 1,
                "resource_id": rid,
                "resource_name": str(meta.get("resource_name") or meta.get("label") or rid),
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
    district_token = login_with_fallback("district_603", ["district123", "pw"])
    state_token = login_with_fallback("state_33", ["state123", "pw"])
    neighbor_token = login_with_fallback("state_32", ["state123", "pw"])
    national_token = login_with_fallback("national_admin", ["national123", "pw"])

    resources = get_json("/metadata/resources", district_token)
    stock_rows = get_json("/district/stock", district_token)
    cases = build_cases(stock_rows, resources, TOTAL_CASES)

    report: dict[str, Any] = {
        "started_at": now_iso(),
        "cases_planned": len(cases),
        "requests": [],
        "waves": [],
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
            timeout=50,
        )
        report["requests"].append({
            **case,
            "request_status": status,
            "request_body": body,
            "request_id": int(body.get("request_id") or 0) if isinstance(body, dict) else 0,
        })

    accepted = [r for r in report["requests"] if int(r.get("request_status") or 0) in {200, 201}]

    for i in range(0, len(accepted), WAVE_SIZE):
        wave_cases = accepted[i:i + WAVE_SIZE]
        wave_ids = {int(x.get("request_id") or 0) for x in wave_cases}

        trigger_status, trigger_body = post_json("/district/run", district_token, {}, timeout=360)
        run_id = int(trigger_body.get("solver_run_id") or 0) if isinstance(trigger_body, dict) else 0
        run_status = wait_for_run_completion(district_token, run_id, max_wait_s=420) if run_id else {}

        allocations = get_json("/district/allocations", district_token)
        wave_alloc = [
            r for r in allocations
            if int(r.get("solver_run_id") or 0) == int(run_id)
            and int(r.get("request_id") or 0) in wave_ids
            and float(r.get("allocated_quantity") or 0.0) > 0.0
        ]

        by_scope = {"district": 0.0, "state": 0.0, "neighbor_state": 0.0, "national": 0.0}
        for r in wave_alloc:
            scope = str(r.get("allocation_source_scope") or r.get("supply_level") or "district").lower()
            qty = float(r.get("allocated_quantity") or 0.0)
            if scope not in by_scope:
                scope = "district"
            by_scope[scope] += qty

        state_escalations = get_json("/state/escalations", state_token)
        national_escalations = get_json("/national/escalations", national_token)
        market = get_json("/state/mutual-aid/market", neighbor_token)

        wave = {
            "wave_index": (i // WAVE_SIZE) + 1,
            "run_id": run_id,
            "trigger_status": trigger_status,
            "run_status": run_status,
            "request_ids": sorted(list(wave_ids)),
            "scope_allocations": by_scope,
            "state_escalations_seen": len([x for x in (state_escalations if isinstance(state_escalations, list) else []) if int(x.get("id") or 0) in wave_ids]),
            "national_escalations_seen": len([x for x in (national_escalations if isinstance(national_escalations, list) else []) if int(x.get("id") or 0) in wave_ids]),
            "neighbor_market_hits": len([x for x in (market if isinstance(market, list) else []) if int(x.get("id") or 0) in wave_ids]),
        }
        report["waves"].append(wave)

    scope_totals = {"district": 0.0, "state": 0.0, "neighbor_state": 0.0, "national": 0.0}
    for w in report["waves"]:
        for k in scope_totals.keys():
            scope_totals[k] += float((w.get("scope_allocations") or {}).get(k) or 0.0)

    report["completed_at"] = now_iso()
    report["summary"] = {
        "accepted_requests": len(accepted),
        "waves": len(report["waves"]),
        "scope_totals": scope_totals,
        "state_or_neighbor_seen": bool(scope_totals["state"] > 0 or scope_totals["neighbor_state"] > 0),
        "national_seen": bool(scope_totals["national"] > 0),
    }

    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Live Auto Escalation 30 Quantity-Only Report",
        "",
        f"- accepted_requests: {report['summary']['accepted_requests']}",
        f"- waves: {report['summary']['waves']}",
        f"- district_alloc: {scope_totals['district']:.2f}",
        f"- state_alloc: {scope_totals['state']:.2f}",
        f"- neighbor_alloc: {scope_totals['neighbor_state']:.2f}",
        f"- national_alloc: {scope_totals['national']:.2f}",
        f"- state_or_neighbor_seen: {report['summary']['state_or_neighbor_seen']}",
        f"- national_seen: {report['summary']['national_seen']}",
        "",
        "| Wave | Run | ReqCount | District | State | Neighbor | National | StateEsc | NatEsc | NeighborMarket |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for w in report["waves"]:
        sc = w.get("scope_allocations") or {}
        lines.append(
            f"| {w.get('wave_index')} | {w.get('run_id')} | {len(w.get('request_ids') or [])} | {float(sc.get('district') or 0):.2f} | {float(sc.get('state') or 0):.2f} | {float(sc.get('neighbor_state') or 0):.2f} | {float(sc.get('national') or 0):.2f} | {w.get('state_escalations_seen')} | {w.get('national_escalations_seen')} | {w.get('neighbor_market_hits')} |"
        )

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({
        "json_report": str(OUT_JSON.resolve()),
        "md_report": str(OUT_MD.resolve()),
        "summary": report["summary"],
    }, indent=2))


if __name__ == "__main__":
    main()
