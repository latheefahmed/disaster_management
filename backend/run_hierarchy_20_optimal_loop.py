from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import requests

BASE = "http://127.0.0.1:8000"
TOTAL_CASES = max(1, int(os.getenv("HIERARCHY_TOTAL_CASES", "20") or 20))
WAVE_SIZE = max(1, int(os.getenv("HIERARCHY_WAVE_SIZE", "5") or 5))
MAX_ATTEMPTS = max(1, int(os.getenv("HIERARCHY_MAX_ATTEMPTS", "3") or 3))
OUT_JSON = Path("HIERARCHY_20_OPTIMAL_LOOP_REPORT.json")
OUT_MD = Path("HIERARCHY_20_OPTIMAL_LOOP_REPORT.md")
DB_PATH = Path("backend.db")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def login_with_fallback(username: str, passwords: list[str]) -> str:
    err = None
    for pw in passwords:
        try:
            r = requests.post(f"{BASE}/auth/login", json={"username": username, "password": pw}, timeout=25)
            r.raise_for_status()
            return r.json()["access_token"]
        except Exception as e:
            err = e
    raise RuntimeError(f"login failed for {username}: {err}")


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_json(path: str, token: str, params: dict[str, Any] | None = None, timeout: int = 60) -> Any:
    r = requests.get(f"{BASE}{path}", headers=headers(token), params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def post_json(path: str, token: str, payload: dict[str, Any], timeout: int = 120) -> tuple[int, Any]:
    r = requests.post(f"{BASE}{path}", headers=headers(token), json=payload, timeout=timeout)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    return r.status_code, body


def normalize_qty(meta: dict[str, Any], qty: float) -> float:
    max_reasonable = float(meta.get("max_reasonable_quantity") or meta.get("max_per_resource") or 1_000_000)
    bounded = max(2.0, min(float(qty), max_reasonable))
    count_type = str(meta.get("count_type") or "").lower()
    if bool(meta.get("requires_integer_quantity")) or count_type == "integer":
        bounded = float(int(round(bounded)))
        if bounded < 2:
            bounded = 2.0
    return bounded


def wait_run(token: str, run_id: int, max_wait_s: int = 480) -> dict[str, Any]:
    started = time.time()
    last = {}
    while time.time() - started < max_wait_s:
        rows = get_json("/district/run-history", token)
        if isinstance(rows, list):
            row = next((r for r in rows if int(r.get("run_id") or 0) == int(run_id)), None)
            if row:
                last = row
                status = str(row.get("status") or "").lower()
                if status in {"completed", "failed", "failed_reconciliation"}:
                    return row
        time.sleep(2)
    return last


def return_previous_resources(run_tag: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["EXCLUDE_LAST_RUNS"] = "0"
    env["RETURN_RUN_TAG"] = run_tag
    cmd = [sys.executable, "return_resources_excluding_last_10_runs.py"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)

    report_path = Path("RETURN_RESOURCES_EXCEPT_LAST10_REPORT.json")
    payload: dict[str, Any] = {
        "status": "unknown",
        "exit_code": int(proc.returncode),
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }
    if report_path.exists():
        try:
            payload.update(json.loads(report_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return payload


def latest_failure_reason(run_id: int) -> str | None:
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT summary_snapshot_json FROM solver_runs WHERE id=?", (int(run_id),))
    row = cur.fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        data = json.loads(str(row[0]))
        if isinstance(data, dict):
            return str(data.get("failure_reason") or data.get("error") or "") or None
    except Exception:
        return None
    return None


def join_request_allocation_diagnostics(run_id: int, request_ids: list[int]) -> dict[str, Any]:
    if not DB_PATH.exists() or not request_ids:
        return {
            "priority_time_checks": {
                "high_priority_early_non_district_qty": 0.0,
                "low_priority_late_national_qty": 0.0,
            },
            "status_counts": {},
            "state_escalated_no_response": 0,
            "unmet_rows": 0,
            "unmet_qty": 0.0,
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in request_ids)

    cur.execute(
        f"""
        SELECT id, priority, urgency, time, status, COALESCE(unmet_quantity,0.0) AS unmet_quantity
        FROM requests
        WHERE id IN ({placeholders})
        """,
        tuple(request_ids),
    )
    req_rows = [dict(r) for r in cur.fetchall()]

    cur.execute(
        f"""
        SELECT a.request_id, COALESCE(a.allocation_source_scope, a.supply_level, 'district') AS source_scope,
               COALESCE(a.allocated_quantity,0.0) AS qty, COALESCE(a.is_unmet,0) AS is_unmet
        FROM allocations a
        WHERE a.solver_run_id = ?
          AND a.request_id IN ({placeholders})
        """,
        (int(run_id), *request_ids),
    )
    alloc_rows = [dict(r) for r in cur.fetchall()]

    req_map = {int(r["id"]): r for r in req_rows}
    high_priority_early_non_district_qty = 0.0
    low_priority_late_national_qty = 0.0
    unmet_rows = 0
    unmet_qty = 0.0

    for a in alloc_rows:
        req = req_map.get(int(a["request_id"]))
        if req is None:
            continue
        qty = float(a.get("qty") or 0.0)
        source_scope = str(a.get("source_scope") or "district").lower()
        if int(a.get("is_unmet") or 0) == 1:
            unmet_rows += 1
            unmet_qty += qty
            continue

        priority = int(req.get("priority") or 0)
        time_idx = int(req.get("time") or 0)

        if priority >= 4 and time_idx <= 1 and source_scope in {"state", "neighbor_state", "national"}:
            high_priority_early_non_district_qty += qty

        if priority <= 2 and time_idx >= 2 and source_scope == "national":
            low_priority_late_national_qty += qty

    status_counts: dict[str, int] = {}
    for r in req_rows:
        key = str(r.get("status") or "unknown").lower()
        status_counts[key] = status_counts.get(key, 0) + 1

    state_escalated_no_response = 0
    alloc_req_ids = {int(a["request_id"]) for a in alloc_rows if int(a.get("is_unmet") or 0) == 0}
    for r in req_rows:
        if str(r.get("status") or "").lower() == "escalated_state" and int(r["id"]) not in alloc_req_ids:
            state_escalated_no_response += 1

    conn.close()

    return {
        "priority_time_checks": {
            "high_priority_early_non_district_qty": float(round(high_priority_early_non_district_qty, 3)),
            "low_priority_late_national_qty": float(round(low_priority_late_national_qty, 3)),
        },
        "status_counts": status_counts,
        "state_escalated_no_response": int(state_escalated_no_response),
        "unmet_rows": int(unmet_rows),
        "unmet_qty": float(round(unmet_qty, 3)),
    }


def build_cases(stock_rows: list[dict[str, Any]], resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    meta_map = {str(r.get("resource_id")): r for r in resources if isinstance(r, dict)}
    rows = [r for r in stock_rows if str(r.get("resource_id")) in meta_map and float(r.get("available_stock") or 0.0) > 0]
    rows.sort(key=lambda x: float(x.get("available_stock") or 0.0), reverse=True)
    if not rows:
        return []

    state_favor = [
        r for r in rows
        if float(r.get("state_stock") or 0.0) > 0.0
        and float(r.get("district_stock") or 0.0) <= float(r.get("state_stock") or 0.0) * 0.75
    ]
    national_favor = [
        r for r in rows
        if float(r.get("national_stock") or 0.0) > 0.0
        and (float(r.get("district_stock") or 0.0) + float(r.get("state_stock") or 0.0)) <= float(r.get("national_stock") or 0.0) * 0.9
    ]
    balanced = [
        r for r in rows
        if float(r.get("district_stock") or 0.0) > 0.0 and float(r.get("state_stock") or 0.0) > 0.0
    ]

    if not state_favor:
        state_favor = rows
    if not national_favor:
        national_favor = rows
    if not balanced:
        balanced = rows

    variants = [
        "urgent_fast_state_neighbor_first",
        "urgent_fast_state_neighbor_first",
        "balanced_mid",
        "low_late_direct_national",
        "low_late_direct_national",
    ]

    cases: list[dict[str, Any]] = []
    for i in range(TOTAL_CASES):
        variant = variants[i % len(variants)]
        if variant == "urgent_fast_state_neighbor_first":
            row = state_favor[i % len(state_favor)]
        elif variant == "low_late_direct_national":
            row = national_favor[i % len(national_favor)]
        else:
            row = balanced[i % len(balanced)]

        rid = str(row.get("resource_id"))
        meta = meta_map[rid]

        d = float(row.get("district_stock") or 0.0)
        s = float(row.get("state_stock") or 0.0)
        n = float(row.get("national_stock") or 0.0)
        a = float(row.get("available_stock") or 0.0)

        if variant == "urgent_fast_state_neighbor_first":
            time_idx = 0
            priority = 5
            urgency = 5
            desired = d + max(30.0, min(max(s * 0.95, 45.0), max(90.0, a * 0.12)))
        elif variant == "low_late_direct_national":
            time_idx = 3
            priority = 1
            urgency = 1
            desired = d + s + max(40.0, min(max(n * 0.30, 70.0), max(120.0, a * 0.24)))
        else:
            time_idx = 1
            priority = 3
            urgency = 3
            desired = d + max(10.0, min(max(s * 0.5, 20.0), max(40.0, a * 0.06)))

        qty = normalize_qty(meta, desired)
        cases.append(
            {
                "case_id": i + 1,
                "variant": variant,
                "resource_id": rid,
                "resource_name": str(meta.get("resource_name") or meta.get("label") or rid),
                "time": int(time_idx),
                "priority": int(priority),
                "urgency": int(urgency),
                "quantity": float(qty),
                "pre_stock": {"district": d, "state": s, "national": n, "available": a},
            }
        )

    return cases


def run_wave(district_token: str, state_token: str, national_token: str, wave_cases: list[dict[str, Any]]) -> dict[str, Any]:
    request_ids: list[int] = []
    req_rows = []

    for c in wave_cases:
        status, body = post_json(
            "/district/request",
            district_token,
            {
                "resource_id": c["resource_id"],
                "time": int(c["time"]),
                "quantity": float(c["quantity"]),
                "priority": int(c["priority"]),
                "urgency": int(c["urgency"]),
                "confidence": 1.0,
                "source": "human",
            },
            timeout=60,
        )
        rid = int(body.get("request_id") or 0) if isinstance(body, dict) else 0
        if rid > 0 and status in {200, 201}:
            request_ids.append(rid)
        req_rows.append({**c, "request_status": status, "request_id": rid})

    trig_status, trig_body = post_json("/district/run", district_token, {}, timeout=360)
    run_id = int(trig_body.get("solver_run_id") or 0) if isinstance(trig_body, dict) else 0
    run_status = wait_run(district_token, run_id, max_wait_s=480) if run_id else {}

    alloc_rows = get_json("/district/allocations", district_token)
    req_set = set(request_ids)
    alloc_rows = [
        r for r in alloc_rows
        if int(r.get("solver_run_id") or 0) == int(run_id)
        and (int(r.get("request_id") or 0) in req_set or int(r.get("source_request_id") or 0) in req_set)
    ]

    scope = {"district": 0.0, "state": 0.0, "neighbor_state": 0.0, "national": 0.0}
    unmet_qty = 0.0
    for r in alloc_rows:
        qty = float(r.get("allocated_quantity") or 0.0)
        if bool(r.get("is_unmet")):
            unmet_qty += qty
            continue
        key = str(r.get("allocation_source_scope") or r.get("supply_level") or "district").lower()
        if key not in scope:
            key = "district"
        scope[key] += qty

    state_esc = get_json("/state/escalations", state_token)
    national_esc = get_json("/national/escalations", national_token)

    state_seen = len([x for x in (state_esc if isinstance(state_esc, list) else []) if int(x.get("id") or 0) in req_set])
    nat_seen = len([x for x in (national_esc if isinstance(national_esc, list) else []) if int(x.get("id") or 0) in req_set])

    status_txt = str((run_status or {}).get("status") or "").lower()
    failure_reason = None
    if status_txt in {"failed", "failed_reconciliation"}:
        failure_reason = latest_failure_reason(run_id)

    diagnostics = join_request_allocation_diagnostics(run_id, sorted(list(req_set)))

    return {
        "request_rows": req_rows,
        "request_ids": sorted(list(req_set)),
        "run_id": run_id,
        "run_status": run_status,
        "trigger_status": trig_status,
        "scope": scope,
        "unmet_qty": float(unmet_qty),
        "state_escalations_seen": int(state_seen),
        "national_escalations_seen": int(nat_seen),
        "failure_reason": failure_reason,
        "diagnostics": diagnostics,
        "acceptable_run_outcome": bool(status_txt in {"completed", "failed", "failed_reconciliation"}),
    }


def run_attempt(attempt_no: int) -> dict[str, Any]:
    district_token = login_with_fallback("district_603", ["district123", "pw"])
    state_token = login_with_fallback("state_33", ["state123", "pw"])
    national_token = login_with_fallback("national_admin", ["national123", "pw"])

    resources = get_json("/metadata/resources", district_token)
    stock_rows = get_json("/district/stock", district_token)
    cases = build_cases(stock_rows, resources)

    attempt_report: dict[str, Any] = {
        "attempt": int(attempt_no),
        "started_at": now_iso(),
        "cases_planned": len(cases),
        "wave_size": WAVE_SIZE,
        "waves": [],
    }

    for i in range(0, len(cases), WAVE_SIZE):
        wave_cases = cases[i:i + WAVE_SIZE]
        out = run_wave(district_token, state_token, national_token, wave_cases)
        out["wave_index"] = (i // WAVE_SIZE) + 1
        attempt_report["waves"].append(out)

    totals = {"district": 0.0, "state": 0.0, "neighbor_state": 0.0, "national": 0.0}
    unmet_total = 0.0
    state_seen_total = 0
    national_seen_total = 0
    high_priority_early_non_district_qty = 0.0
    low_priority_late_national_qty = 0.0
    state_escalated_no_response_total = 0
    failed_runs: list[dict[str, Any]] = []

    for w in attempt_report["waves"]:
        sc = w.get("scope") or {}
        for k in totals:
            totals[k] += float(sc.get(k) or 0.0)
        unmet_total += float(w.get("unmet_qty") or 0.0)
        state_seen_total += int(w.get("state_escalations_seen") or 0)
        national_seen_total += int(w.get("national_escalations_seen") or 0)

        d = w.get("diagnostics") or {}
        pt = d.get("priority_time_checks") or {}
        high_priority_early_non_district_qty += float(pt.get("high_priority_early_non_district_qty") or 0.0)
        low_priority_late_national_qty += float(pt.get("low_priority_late_national_qty") or 0.0)
        state_escalated_no_response_total += int(d.get("state_escalated_no_response") or 0)

        st = str((w.get("run_status") or {}).get("status") or "").lower()
        if st in {"failed", "failed_reconciliation"}:
            failed_runs.append({
                "run_id": int(w.get("run_id") or 0),
                "status": st,
                "failure_reason": w.get("failure_reason"),
            })

    policy_check = {
        "high_priority_early_prefers_escalation": bool(high_priority_early_non_district_qty > 0.0),
        "low_priority_late_allows_direct_national": bool(low_priority_late_national_qty > 0.0),
        "state_or_neighbor_used": bool((totals["state"] + totals["neighbor_state"]) > 0.0),
        "national_used": bool(totals["national"] > 0.0),
    }

    attempt_report["completed_at"] = now_iso()
    attempt_report["summary"] = {
        "waves": len(attempt_report["waves"]),
        "scope_totals": {k: float(round(v, 3)) for k, v in totals.items()},
        "unmet_total": float(round(unmet_total, 3)),
        "state_escalations_seen_total": int(state_seen_total),
        "national_escalations_seen_total": int(national_seen_total),
        "state_escalated_no_response_total": int(state_escalated_no_response_total),
        "priority_time_checks": {
            "high_priority_early_non_district_qty": float(round(high_priority_early_non_district_qty, 3)),
            "low_priority_late_national_qty": float(round(low_priority_late_national_qty, 3)),
        },
        "failed_runs": failed_runs,
        "policy_check": policy_check,
    }

    attempt_report["is_optimal"] = bool(
        len(failed_runs) == 0
        and policy_check["state_or_neighbor_used"]
        and policy_check["national_used"]
        and policy_check["high_priority_early_prefers_escalation"]
        and policy_check["low_priority_late_allows_direct_national"]
    )

    return attempt_report


def main():
    full_report: dict[str, Any] = {
        "started_at": now_iso(),
        "max_attempts": MAX_ATTEMPTS,
        "total_cases": TOTAL_CASES,
        "wave_size": WAVE_SIZE,
        "attempts": [],
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        rollback = return_previous_resources(run_tag=f"attempt_{attempt}")
        attempt_report = run_attempt(attempt)
        attempt_report["pre_attempt_return"] = rollback
        full_report["attempts"].append(attempt_report)

        if bool(attempt_report.get("is_optimal")):
            break

    full_report["completed_at"] = now_iso()
    full_report["final_attempt"] = full_report["attempts"][-1] if full_report["attempts"] else None
    full_report["overall_optimal"] = bool((full_report.get("final_attempt") or {}).get("is_optimal"))

    OUT_JSON.write_text(json.dumps(full_report, indent=2), encoding="utf-8")

    lines = [
        "# Hierarchy 20 Optimal Loop Report",
        "",
        f"- attempts_run: {len(full_report['attempts'])}",
        f"- overall_optimal: {full_report['overall_optimal']}",
        "",
    ]

    for a in full_report["attempts"]:
        s = a.get("summary") or {}
        sc = s.get("scope_totals") or {}
        lines.extend([
            f"## Attempt {a.get('attempt')}",
            f"- is_optimal: {a.get('is_optimal')}",
            f"- district_alloc: {float(sc.get('district') or 0):.2f}",
            f"- state_alloc: {float(sc.get('state') or 0):.2f}",
            f"- neighbor_alloc: {float(sc.get('neighbor_state') or 0):.2f}",
            f"- national_alloc: {float(sc.get('national') or 0):.2f}",
            f"- unmet_total: {float(s.get('unmet_total') or 0):.2f}",
            f"- state_escalated_no_response_total: {int(s.get('state_escalated_no_response_total') or 0)}",
            f"- failed_runs: {len(s.get('failed_runs') or [])}",
            "",
        ])

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({
        "json_report": str(OUT_JSON.resolve()),
        "md_report": str(OUT_MD.resolve()),
        "overall_optimal": full_report["overall_optimal"],
        "attempts_run": len(full_report["attempts"]),
    }, indent=2))


if __name__ == "__main__":
    main()
