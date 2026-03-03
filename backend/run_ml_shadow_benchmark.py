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
OUT_JSON = Path("DISTRICT603_LIVE_CAMPAIGN_REPORT.json")
BENCHMARK_KEY = "ml_shadow_readiness_benchmark"


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
        if str(last.get("status") or "").lower() in {"completed", "failed", "failed_reconciliation"}:
            return last
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


def choose_requests(
    resources: list[dict[str, Any]],
    run_idx: int,
    reqs_per_run: int = 8,
    rankless_ratio: float = 0.0,
) -> list[dict[str, Any]]:
    candidates = [r for r in resources if float(r.get("max_reasonable_quantity") or r.get("max_per_resource") or 0.0) >= 5.0]
    candidates.sort(key=lambda x: str(x.get("resource_id")))
    if not candidates:
        return []

    rng = random.Random(1000 + run_idx)
    picks: list[dict[str, Any]] = []
    for i in range(reqs_per_run):
        meta = candidates[(run_idx * reqs_per_run + i) % len(candidates)]
        rid = str(meta.get("resource_id"))
        t = (run_idx + i) % 5
        q_base = rng.randint(2, 15) * (1 + (i % 3))
        qty = _normalize_qty(meta, float(q_base))
        drop_ranks = rng.random() < max(0.0, min(1.0, float(rankless_ratio)))
        picks.append(
            {
                "resource_id": rid,
                "time": int(t),
                "quantity": qty,
                "priority": (None if drop_ranks else (5 if (i % 4 == 0) else 4)),
                "urgency": (None if drop_ranks else (5 if (t == 0 or i % 5 == 0) else 4)),
                "confidence": 1.0,
                "source": "human",
            }
        )
    return picks


def db_count(con: sqlite3.Connection, table: str) -> int:
    cur = con.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cur.fetchone()[0])


def db_run_metrics(con: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    cur = con.cursor()

    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(allocated_quantity),0.0) FROM allocations WHERE solver_run_id=? AND is_unmet=0",
        (int(run_id),),
    )
    alloc_rows, alloc_qty = cur.fetchone()

    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(allocated_quantity),0.0) FROM allocations WHERE solver_run_id=? AND is_unmet=1",
        (int(run_id),),
    )
    unmet_rows, unmet_qty = cur.fetchone()

    cur.execute(
        "SELECT status, COUNT(*) FROM requests WHERE run_id=? GROUP BY status",
        (int(run_id),),
    )
    req_status = {str(k): int(v) for k, v in cur.fetchall()}

    return {
        "alloc_rows": int(alloc_rows or 0),
        "alloc_qty": float(alloc_qty or 0.0),
        "unmet_rows": int(unmet_rows or 0),
        "unmet_qty": float(unmet_qty or 0.0),
        "request_status_counts": req_status,
    }


def phase_run(label: str, iterations: int, rankless_ratio: float = 0.0) -> dict[str, Any]:
    token = login(*DISTRICT_USER)
    resources = get_json("/metadata/resources", token)

    con = sqlite3.connect("backend.db")

    before = {
        "demand_learning_events": db_count(con, "demand_learning_events"),
        "priority_urgency_events": db_count(con, "priority_urgency_events"),
        "request_predictions": db_count(con, "request_predictions"),
        "demand_weight_models": db_count(con, "demand_weight_models"),
        "priority_urgency_models": db_count(con, "priority_urgency_models"),
        "adaptive_parameters": db_count(con, "adaptive_parameters"),
    }

    runs: list[dict[str, Any]] = []

    for idx in range(iterations):
        req_payloads = choose_requests(resources, run_idx=idx, reqs_per_run=8, rankless_ratio=rankless_ratio)
        req_results = []
        for payload in req_payloads:
            status, body = post_json("/district/request", token, payload, timeout=40)
            req_results.append({"status": status, "body": body, "payload": payload})

        accepted = sum(1 for r in req_results if int(r.get("status") or 0) in {200, 201})

        try:
            trig_status, trig_body = post_json("/district/run", token, {}, timeout=300)
        except Exception as e:
            trig_status, trig_body = 599, {"detail": f"run trigger timeout/error: {e}"}

        solver = wait_solver_completed(token, max_wait_s=300)
        run_id = int(solver.get("solver_run_id") or 0)
        run_db = db_run_metrics(con, run_id=run_id) if run_id > 0 else {}

        runs.append(
            {
                "iteration": idx + 1,
                "requests_total": len(req_results),
                "requests_accepted": accepted,
                "run_trigger_status": trig_status,
                "solver_status": solver,
                "run_db": run_db,
            }
        )

    after = {
        "demand_learning_events": db_count(con, "demand_learning_events"),
        "priority_urgency_events": db_count(con, "priority_urgency_events"),
        "request_predictions": db_count(con, "request_predictions"),
        "demand_weight_models": db_count(con, "demand_weight_models"),
        "priority_urgency_models": db_count(con, "priority_urgency_models"),
        "adaptive_parameters": db_count(con, "adaptive_parameters"),
    }

    con.close()

    completed = [r for r in runs if str((r.get("solver_status") or {}).get("status") or "").lower() == "completed"]
    failed = [r for r in runs if str((r.get("solver_status") or {}).get("status") or "").lower() == "failed"]

    unmet_rate_avg = 0.0
    alloc_rate_avg = 0.0
    if completed:
        unmet_vals = []
        alloc_vals = []
        for row in completed:
            dbm = row.get("run_db") or {}
            alloc_rows = float(dbm.get("alloc_rows") or 0.0)
            unmet_rows = float(dbm.get("unmet_rows") or 0.0)
            total = alloc_rows + unmet_rows
            if total > 0:
                unmet_vals.append(unmet_rows / total)
                alloc_vals.append(alloc_rows / total)
        if unmet_vals:
            unmet_rate_avg = sum(unmet_vals) / len(unmet_vals)
        if alloc_vals:
            alloc_rate_avg = sum(alloc_vals) / len(alloc_vals)

    artifacts_delta = {k: int(after[k] - before[k]) for k in before}

    return {
        "label": label,
        "started_at": now_iso(),
        "iterations": iterations,
        "rankless_ratio": float(rankless_ratio),
        "runs": runs,
        "summary": {
            "runs_completed": len(completed),
            "runs_failed": len(failed),
            "requests_accepted_total": sum(int(r.get("requests_accepted") or 0) for r in runs),
            "requests_total": sum(int(r.get("requests_total") or 0) for r in runs),
            "avg_unmet_row_rate": round(unmet_rate_avg, 6),
            "avg_alloc_row_rate": round(alloc_rate_avg, 6),
        },
        "artifacts_before": before,
        "artifacts_after": after,
        "artifacts_delta": artifacts_delta,
        "ended_at": now_iso(),
    }


def append_report(phase: dict[str, Any]) -> None:
    report = json.loads(OUT_JSON.read_text(encoding="utf-8")) if OUT_JSON.exists() else {}
    existing = report.get(BENCHMARK_KEY) or {}
    phases = list(existing.get("phases") or [])
    phases.append(phase)
    existing["phases"] = phases
    existing["updated_at"] = now_iso()
    report[BENCHMARK_KEY] = existing
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--rankless-ratio", type=float, default=0.0)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()

    phase = phase_run(
        label=str(args.label),
        iterations=int(args.iterations),
        rankless_ratio=float(args.rankless_ratio),
    )
    if args.append:
        append_report(phase)

    print(json.dumps(phase["summary"], indent=2))
    print(json.dumps(phase["artifacts_delta"], indent=2))


if __name__ == "__main__":
    main()
