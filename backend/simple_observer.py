from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_BACKEND = "http://127.0.0.1:8000"
BASE_FRONTEND = "http://127.0.0.1:5173"
DB_PATH = Path(__file__).parent / "backend.db"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def check_http(url: str, timeout: float = 2.5) -> tuple[bool, str]:
    try:
        r = requests.get(url, timeout=timeout)
        return True, str(r.status_code)
    except Exception as exc:
        return False, f"err:{type(exc).__name__}"


def get_last_run_snapshot() -> dict[str, str]:
    if not DB_PATH.exists():
        return {"last_run": "n/a", "status": "n/a", "pending_requests": "n/a"}

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    try:
        cur.execute("SELECT id, status FROM solver_runs ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            con.close()
            return {"last_run": "none", "status": "none", "pending_requests": "0"}

        run_id = int(row[0])
        status = str(row[1])

        cur.execute(
            "SELECT COUNT(1) FROM requests WHERE run_id=? AND LOWER(COALESCE(status,'')) IN ('new','solving')",
            (run_id,),
        )
        pending = int(cur.fetchone()[0] or 0)

        con.close()
        return {
            "last_run": str(run_id),
            "status": status,
            "pending_requests": str(pending),
        }
    except Exception:
        con.close()
        return {"last_run": "unknown", "status": "unknown", "pending_requests": "unknown"}


def print_line() -> None:
    backend_ok, backend_code = check_http(f"{BASE_BACKEND}/metadata/states")
    frontend_ok, frontend_code = check_http(BASE_FRONTEND)
    run = get_last_run_snapshot()

    print(
        f"[{now_str()}] "
        f"backend={'UP' if backend_ok else 'DOWN'}({backend_code}) | "
        f"frontend={'UP' if frontend_ok else 'DOWN'}({frontend_code}) | "
        f"run={run['last_run']} status={run['status']} pending={run['pending_requests']}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Lightweight observer for frontend/backend and last solver run")
    parser.add_argument("--interval", type=float, default=3.0, help="Polling interval in seconds (default: 3)")
    parser.add_argument("--once", action="store_true", help="Print one snapshot and exit")
    args = parser.parse_args()

    if args.once:
        print_line()
        return

    while True:
        print_line()
        time.sleep(max(0.5, args.interval))


if __name__ == "__main__":
    main()
