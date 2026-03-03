import json
import statistics
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi.testclient import TestClient

os.environ.setdefault("APP_SKIP_RUNTIME_MIGRATIONS", "true")
os.environ.setdefault("APP_DISABLE_PROJECTOR", "true")

from app.main import app

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


def login_token(client: TestClient, role: str):
    started = time.perf_counter()
    res = client.post("/auth/login", json=USERS[role])
    elapsed = (time.perf_counter() - started) * 1000.0
    res.raise_for_status()
    token = res.json().get("access_token")
    if not token:
        raise RuntimeError(f"no token for role={role}")
    return token, elapsed


def do_call(client: TestClient, role: str, token: str, path: str):
    started = time.perf_counter()
    status = None
    error = None
    try:
        res = client.get(path, headers={"Authorization": f"Bearer {token}"})
        status = int(res.status_code)
    except Exception as exc:
        error = str(exc)
    elapsed = (time.perf_counter() - started) * 1000.0
    return {
        "role": role,
        "path": path,
        "status": status,
        "latency_ms": elapsed,
        "error": error,
    }


def summarize(rows):
    grouped = {}
    failures = []
    for row in rows:
        key = f"{row['role']}:{row['path']}"
        if row["status"] != 200:
            failures.append(row)
            continue
        grouped.setdefault(key, []).append(float(row["latency_ms"]))

    endpoints = {}
    all_vals = []
    for key, vals in grouped.items():
        all_vals.extend(vals)
        endpoints[key] = {
            "count": len(vals),
            "p50_ms": statistics.median(vals),
            "p95_ms": sorted(vals)[max(0, int(len(vals) * 0.95) - 1)],
            "max_ms": max(vals),
            "avg_ms": statistics.fmean(vals),
        }

    overall = {
        "count": len(all_vals),
        "p50_ms": statistics.median(all_vals) if all_vals else None,
        "p95_ms": sorted(all_vals)[max(0, int(len(all_vals) * 0.95) - 1)] if all_vals else None,
        "max_ms": max(all_vals) if all_vals else None,
        "avg_ms": statistics.fmean(all_vals) if all_vals else None,
    }
    return {"overall": overall, "endpoints": endpoints, "failures": failures}


def main():
    client = TestClient(app)
    tokens = {}
    login_ms = {}

    for role in USERS:
        tok, elapsed = login_token(client, role)
        tokens[role] = tok
        login_ms[role] = elapsed

    jobs = []
    for _ in range(4):
        jobs.extend(MATRIX)

    rows = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(do_call, client, role, tokens[role], path) for role, path in jobs]
        for fut in as_completed(futures):
            rows.append(fut.result())
    total_ms = (time.perf_counter() - started) * 1000.0

    print(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "login_ms": login_ms,
        "probe_total_ms": total_ms,
        "summary": summarize(rows),
    }, indent=2))


if __name__ == "__main__":
    main()
