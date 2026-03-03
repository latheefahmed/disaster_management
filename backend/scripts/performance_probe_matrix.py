import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE = "http://127.0.0.1:8000"
TIMEOUT = 30

USERS = {
    "district": {"username": "district_603", "password": "district123"},
    "state": {"username": "state_33", "password": "state123"},
    "national": {"username": "national_admin", "password": "national123"},
    "admin": {"username": "admin", "password": "admin123"},
}

MATRIX = [
    ("district", "/district/kpis"),
    ("district", "/district/allocations"),
    ("district", "/district/run-history"),
    ("state", "/state/allocations/summary"),
    ("state", "/state/run-history"),
    ("state", "/state/pool"),
    ("national", "/national/allocations/summary"),
    ("national", "/national/run-history"),
    ("national", "/national/pool"),
    ("admin", "/admin/agent/recommendations"),
]


def login(role: str) -> tuple[str, float]:
    started = time.perf_counter()
    res = requests.post(f"{BASE}/auth/login", json=USERS[role], timeout=TIMEOUT)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    res.raise_for_status()
    token = res.json().get("access_token")
    if not token:
        raise RuntimeError(f"login failed for {role}: no token")
    return token, elapsed_ms


def call(role: str, token: str, path: str) -> dict:
    started = time.perf_counter()
    status = None
    err = None
    try:
        res = requests.get(
            f"{BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
        status = int(res.status_code)
    except Exception as exc:
        err = str(exc)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "role": role,
        "path": path,
        "status": status,
        "latency_ms": elapsed_ms,
        "error": err,
    }


def summarize(rows: list[dict]) -> dict:
    by_key: dict[str, list[float]] = {}
    failures: list[dict] = []
    for row in rows:
        key = f"{row['role']}:{row['path']}"
        if row.get("status") != 200:
            failures.append(row)
            continue
        by_key.setdefault(key, []).append(float(row["latency_ms"]))

    endpoint_stats = {}
    for key, vals in by_key.items():
        endpoint_stats[key] = {
            "count": len(vals),
            "p50_ms": statistics.median(vals),
            "p95_ms": sorted(vals)[max(0, int(len(vals) * 0.95) - 1)],
            "max_ms": max(vals),
            "avg_ms": statistics.fmean(vals),
        }

    all_vals = [float(r["latency_ms"]) for r in rows if r.get("status") == 200]
    overall = {
        "count": len(all_vals),
        "p50_ms": statistics.median(all_vals) if all_vals else None,
        "p95_ms": sorted(all_vals)[max(0, int(len(all_vals) * 0.95) - 1)] if all_vals else None,
        "max_ms": max(all_vals) if all_vals else None,
        "avg_ms": statistics.fmean(all_vals) if all_vals else None,
    }

    return {
        "overall": overall,
        "endpoints": endpoint_stats,
        "failures": failures,
    }


def main():
    tokens = {}
    login_ms = {}
    for role in USERS:
        token, elapsed = login(role)
        tokens[role] = token
        login_ms[role] = elapsed

    work = []
    for _ in range(4):
        work.extend([(role, path) for role, path in MATRIX])

    rows = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(call, role, tokens[role], path) for role, path in work]
        for fut in as_completed(futures):
            rows.append(fut.result())
    total_ms = (time.perf_counter() - started) * 1000.0

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "login_ms": login_ms,
        "total_probe_ms": total_ms,
        "summary": summarize(rows),
        "samples": rows,
    }

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
