from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import atexit
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE_URL = "http://127.0.0.1:8000"
DB_PATH = Path(__file__).parent / "backend.db"
LOG_PATH = Path(__file__).parent / "BACKEND_AUTONOMOUS_GATEWAY_LOG.jsonl"
SUMMARY_PATH = Path(__file__).parent / "BACKEND_AUTONOMOUS_GATEWAY_SUMMARY.json"
LOCK_PATH = Path(__file__).parent / "BACKEND_AUTONOMOUS_GATEWAY_MONITOR.lock"


ROLE_CREDS = {
    "district": ("district_603", "district123"),
    "state": ("state_33", "state123"),
    "national": ("national_admin", "national123"),
    "admin": ("admin", "admin123"),
}

ROLE_ENDPOINTS: dict[str, list[str]] = {
    "district": [
        "/district/kpis",
        "/district/allocations",
        "/district/unmet",
        "/district/claims",
        "/district/returns",
        "/district/solver-status",
    ],
    "state": [
        "/state/kpis",
        "/state/allocations",
        "/state/allocations/summary",
        "/state/run-history",
        "/state/escalations",
        "/state/pool",
    ],
    "national": [
        "/national/kpis",
        "/national/allocations",
        "/national/allocations/summary",
        "/national/run-history",
        "/national/escalations",
        "/national/pool",
    ],
    "admin": [
        "/admin/scenarios",
        "/admin/agent/recommendations",
    ],
    "metadata": [
        "/metadata/states",
        "/metadata/districts",
        "/metadata/resources",
        "/metadata/read-model/national",
    ],
}

STARTUP_ENDPOINTS: dict[str, list[str]] = {
    "district": ["/district/kpis"],
    "state": ["/state/kpis"],
    "national": ["/national/kpis"],
    "admin": ["/admin/scenarios"],
    "metadata": ["/metadata/states"],
}


@dataclass
class BackendProcess:
    proc: subprocess.Popen[str] | None = None


class GatewayMonitor:
    def __init__(self) -> None:
        self.backend = BackendProcess()
        self.tokens: dict[str, str] = {}
        self.last_seen_run_id = 0
        self.session = requests.Session()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def log_event(
        self,
        event_type: str,
        role_context: str,
        run_id: int | None,
        latency_ms: float | None,
        result: str,
        invariant_status: str,
        anomaly_flag: bool,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "timestamp": self.now(),
            "event_type": event_type,
            "role_context": role_context,
            "run_id": run_id,
            "latency_ms": None if latency_ms is None else round(float(latency_ms), 3),
            "result": result,
            "invariant_status": invariant_status,
            "anomaly_flag": bool(anomaly_flag),
            "message": message,
        }
        if extra:
            payload.update(extra)

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def stop_existing_processes(self) -> None:
        cmd = "Get-Process -Name uvicorn -ErrorAction SilentlyContinue | Stop-Process -Force"
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)

    def measure_import_migration_seed(self) -> dict[str, float]:
        venv_py = Path(__file__).parent.parent / ".venv" / "Scripts" / "python.exe"
        py = str(venv_py if venv_py.exists() else Path(sys.executable))

        def _probe(code: str, timeout_s: int) -> tuple[float, str]:
            t0 = time.perf_counter()
            try:
                proc = subprocess.run(
                    [py, "-c", code],
                    cwd=str(Path(__file__).parent),
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    check=False,
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                return elapsed_ms, "ok" if proc.returncode == 0 else f"rc_{proc.returncode}"
            except subprocess.TimeoutExpired:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                return elapsed_ms, "timeout"
            except Exception:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                return elapsed_ms, "exception"

        import_timeout = int(os.getenv("BACKEND_MONITOR_IMPORT_TIMEOUT_SEC", "30"))
        migration_timeout = int(os.getenv("BACKEND_MONITOR_MIGRATION_TIMEOUT_SEC", "45"))
        seed_timeout = int(os.getenv("BACKEND_MONITOR_SEED_TIMEOUT_SEC", "45"))

        import_time_ms, import_status = _probe("import app.main", max(5, import_timeout))
        migration_time_ms, migration_status = _probe(
            "from app.database import apply_runtime_migrations; apply_runtime_migrations()",
            max(5, migration_timeout),
        )
        seed_time_ms, seed_status = _probe("from e2e_seed_data import seed_e2e_data; seed_e2e_data()", max(5, seed_timeout))

        return {
            "import_time_ms": import_time_ms,
            "migration_time_ms": migration_time_ms,
            "seed_time_ms": seed_time_ms,
            "import_status": import_status,
            "migration_status": migration_status,
            "seed_status": seed_status,
        }

    def stale_running_count(self) -> int:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT COUNT(1) FROM solver_runs WHERE mode='live' AND status='running'")
        count = int(cur.fetchone()[0] or 0)
        con.close()
        return count

    def start_backend(self) -> None:
        env = os.environ.copy()
        env["APP_SKIP_RUNTIME_MIGRATIONS"] = "true"
        env["APP_DISABLE_PROJECTOR"] = "true"
        env["PYTHONUNBUFFERED"] = "1"

        self.backend.proc = subprocess.Popen(
            [
                str(Path(__file__).parent.parent / ".venv" / "Scripts" / "python.exe"),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=str(Path(__file__).parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def wait_backend_ready(self, timeout_s: int = 60) -> float:
        started = time.perf_counter()
        while (time.perf_counter() - started) < timeout_s:
            t0 = time.perf_counter()
            try:
                r = self.session.get(f"{BASE_URL}/metadata/states", timeout=5)
                if r.status_code == 200:
                    return (time.perf_counter() - t0) * 1000.0
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("Backend failed to become ready within timeout")

    def login_all_roles(self) -> None:
        for role, (username, password) in ROLE_CREDS.items():
            t0 = time.perf_counter()
            r = self.session.post(
                f"{BASE_URL}/auth/login",
                json={"username": username, "password": password},
                timeout=20,
            )
            latency = (time.perf_counter() - t0) * 1000.0
            ok = r.status_code == 200
            token = None
            if ok:
                token = str(r.json().get("access_token") or "")
                self.tokens[role] = token
            self.log_event(
                event_type="API",
                role_context=role,
                run_id=None,
                latency_ms=latency,
                result=f"login_{r.status_code}",
                invariant_status="ok" if ok else "fail",
                anomaly_flag=not ok,
                message=f"/auth/login for {username}",
            )

    def call_endpoint(self, role: str, path: str) -> None:
        headers = {}
        if role in self.tokens:
            headers["Authorization"] = f"Bearer {self.tokens[role]}"
        t0 = time.perf_counter()
        try:
            api_timeout = int(os.getenv("BACKEND_MONITOR_API_TIMEOUT_SEC", "20"))
            r = self.session.get(f"{BASE_URL}{path}", headers=headers, timeout=max(5, api_timeout))
            latency = (time.perf_counter() - t0) * 1000.0
            row_count = None
            try:
                body = r.json()
                if isinstance(body, list):
                    row_count = len(body)
            except Exception:
                pass
            ok = r.status_code < 500
            self.log_event(
                event_type="API",
                role_context=role,
                run_id=None,
                latency_ms=latency,
                result=f"{r.status_code}",
                invariant_status="ok" if ok else "fail",
                anomaly_flag=not ok,
                message=path,
                extra={"row_count": row_count},
            )
        except Exception as exc:
            self.log_event(
                event_type="API",
                role_context=role,
                run_id=None,
                latency_ms=None,
                result="exception",
                invariant_status="fail",
                anomaly_flag=True,
                message=f"{path}: {exc}",
            )

    def run_api_audit(self, startup_mode: bool = False) -> None:
        endpoint_map = STARTUP_ENDPOINTS if startup_mode else ROLE_ENDPOINTS
        for role in ["district", "state", "national", "admin"]:
            for path in endpoint_map[role]:
                self.call_endpoint(role, path)
        for path in endpoint_map["metadata"]:
            self.call_endpoint("metadata", path)

    def explain_query_plan_checks(self) -> None:
        checks = {
            "state_summary": "EXPLAIN QUERY PLAN SELECT state_code, resource_id, SUM(allocated_quantity) FROM allocations WHERE state_code='33' AND is_unmet=0 GROUP BY state_code, resource_id",
            "district_alloc": "EXPLAIN QUERY PLAN SELECT * FROM allocations WHERE district_code='603' ORDER BY id DESC LIMIT 50",
            "run_history": "EXPLAIN QUERY PLAN SELECT id, status FROM solver_runs WHERE mode='live' ORDER BY id DESC LIMIT 20",
        }

        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        for name, sql in checks.items():
            cur.execute(sql)
            plan_rows = cur.fetchall()
            plan_text = " | ".join(str(r) for r in plan_rows)
            full_scan = "SCAN allocations" in plan_text and "USING INDEX" not in plan_text
            self.log_event(
                event_type="DB",
                role_context="db",
                run_id=None,
                latency_ms=None,
                result="plan_ok" if not full_scan else "plan_scan",
                invariant_status="ok" if not full_scan else "warn",
                anomaly_flag=bool(full_scan),
                message=f"EXPLAIN {name}",
                extra={"plan": plan_text[:1200]},
            )
        con.close()

    def trigger_solver_run(self) -> int | None:
        token = self.tokens.get("district")
        if not token:
            return None
        headers = {"Authorization": f"Bearer {token}"}
        t0 = time.perf_counter()
        r = self.session.post(f"{BASE_URL}/district/run", headers=headers, timeout=45)
        latency = (time.perf_counter() - t0) * 1000.0
        run_id = None
        if r.status_code == 200:
            body = r.json()
            run_id = int(body.get("solver_run_id") or 0)
        self.log_event(
            event_type="SOLVER",
            role_context="district",
            run_id=run_id,
            latency_ms=latency,
            result=str(r.status_code),
            invariant_status="ok" if r.status_code == 200 else "fail",
            anomaly_flag=r.status_code != 200,
            message="trigger /district/run",
        )
        return run_id

    def monitor_run(self, run_id: int, timeout_s: int = 420) -> None:
        started = time.perf_counter()
        token = self.tokens["district"]
        headers = {"Authorization": f"Bearer {token}"}
        final_status = "unknown"

        while (time.perf_counter() - started) < timeout_s:
            t0 = time.perf_counter()
            r = self.session.get(f"{BASE_URL}/district/solver-status", headers=headers, timeout=45)
            latency = (time.perf_counter() - t0) * 1000.0
            if r.status_code != 200:
                self.log_event("SOLVER", "district", run_id, latency, str(r.status_code), "fail", True, "solver-status poll failed")
                time.sleep(2)
                continue
            status = str(r.json().get("status") or "").lower()
            if status in {"completed", "failed", "failed_reconciliation"}:
                final_status = status
                break
            time.sleep(2)

        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(solver_runs)")
        cols = {str(r[1]) for r in cur.fetchall()}

        started_col = "started_at" if "started_at" in cols else ("created_at" if "created_at" in cols else None)
        completed_col = "completed_at" if "completed_at" in cols else ("ended_at" if "ended_at" in cols else None)
        summary_col = "summary_snapshot_json" if "summary_snapshot_json" in cols else None

        sql = (
            "SELECT status, "
            + (f"{started_col}" if started_col else "NULL")
            + ", "
            + (f"{completed_col}" if completed_col else "NULL")
            + ", "
            + (f"{summary_col}" if summary_col else "NULL")
            + " FROM solver_runs WHERE id=?"
        )
        cur.execute(sql, (int(run_id),))
        row = cur.fetchone()
        if row:
            status, started_at, completed_at, snapshot_json = row
            cur.execute(
                "SELECT COALESCE(SUM(demand_quantity),0.0) FROM final_demands WHERE solver_run_id=?",
                (int(run_id),),
            )
            sum_demand = float(cur.fetchone()[0] or 0.0)
            cur.execute(
                "SELECT COALESCE(SUM(allocated_quantity),0.0) FROM allocations WHERE solver_run_id=? AND is_unmet=0",
                (int(run_id),),
            )
            sum_alloc = float(cur.fetchone()[0] or 0.0)
            cur.execute(
                "SELECT COALESCE(SUM(allocated_quantity),0.0) FROM allocations WHERE solver_run_id=? AND is_unmet=1",
                (int(run_id),),
            )
            sum_unmet = float(cur.fetchone()[0] or 0.0)
            conservation_ok = abs((sum_alloc + sum_unmet) - sum_demand) <= 1e-6

            cur.execute(
                "SELECT COUNT(1) FROM requests WHERE run_id=? AND LOWER(COALESCE(status,''))='solving'",
                (int(run_id),),
            )
            solving_left = int(cur.fetchone()[0] or 0)

            self.log_event(
                event_type="SOLVER",
                role_context="district",
                run_id=run_id,
                latency_ms=None,
                result=str(status),
                invariant_status="ok" if (conservation_ok and solving_left == 0 and str(status) == "completed") else "fail",
                anomaly_flag=not (conservation_ok and solving_left == 0 and str(status) == "completed"),
                message="run final audit",
                extra={
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "sum_demand": sum_demand,
                    "sum_alloc": sum_alloc,
                    "sum_unmet": sum_unmet,
                    "conservation_ok": conservation_ok,
                    "solving_left": solving_left,
                    "snapshot_present": bool(snapshot_json),
                    "polled_terminal_status": final_status,
                },
            )

            cur.execute(
                "SELECT supply_level, COUNT(1) FROM allocations WHERE solver_run_id=? GROUP BY supply_level",
                (int(run_id),),
            )
            source_rows = cur.fetchall()
            self.log_event(
                event_type="ESCALATION",
                role_context="district",
                run_id=run_id,
                latency_ms=None,
                result="ok",
                invariant_status="ok",
                anomaly_flag=False,
                message="allocation source distribution",
                extra={"supply_level_counts": {str(k): int(v) for k, v in source_rows}},
            )

        con.close()

    def rapid_micro_burst(self) -> None:
        token = self.tokens.get("district")
        if not token:
            return
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "items": [
                {"resource_id": "R10", "quantity": 5, "time": 0, "priority": 1, "urgency": 1, "confidence": 1.0, "source": "monitor"},
                {"resource_id": "R11", "quantity": 3, "time": 1, "priority": 1, "urgency": 1, "confidence": 1.0, "source": "monitor"},
            ]
        }

        for _ in range(3):
            t0 = time.perf_counter()
            r = self.session.post(f"{BASE_URL}/district/request-batch", headers=headers, json=payload, timeout=45)
            latency = (time.perf_counter() - t0) * 1000.0
            self.log_event(
                event_type="API",
                role_context="district",
                run_id=None,
                latency_ms=latency,
                result=str(r.status_code),
                invariant_status="ok" if r.status_code < 500 else "fail",
                anomaly_flag=r.status_code >= 500,
                message="micro-burst request-batch",
            )

        for _ in range(3):
            rid = self.trigger_solver_run()
            if rid:
                self.monitor_run(rid, timeout_s=420)

    def write_summary(self, startup_metrics: dict[str, float]) -> None:
        summary = {
            "generated_at": self.now(),
            "startup_metrics": startup_metrics,
            "stale_running_after_start": self.stale_running_count(),
            "log_file": str(LOG_PATH),
        }
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    def run_once(self) -> None:
        self.log_event("DB", "startup", None, None, "start", "ok", False, "gateway monitor started")
        self.stop_existing_processes()

        startup_metrics = self.measure_import_migration_seed()
        self.log_event(
            "DB",
            "startup",
            None,
            startup_metrics["import_time_ms"],
            str(startup_metrics.get("import_status", "ok")),
            "ok" if str(startup_metrics.get("import_status", "ok")) == "ok" else "warn",
            str(startup_metrics.get("import_status", "ok")) != "ok",
            "import timing",
        )
        self.log_event(
            "DB",
            "startup",
            None,
            startup_metrics["migration_time_ms"],
            str(startup_metrics.get("migration_status", "ok")),
            "ok" if str(startup_metrics.get("migration_status", "ok")) == "ok" else "warn",
            str(startup_metrics.get("migration_status", "ok")) != "ok",
            "migration timing",
        )
        self.log_event(
            "DB",
            "startup",
            None,
            startup_metrics["seed_time_ms"],
            str(startup_metrics.get("seed_status", "ok")),
            "ok" if str(startup_metrics.get("seed_status", "ok")) == "ok" else "warn",
            str(startup_metrics.get("seed_status", "ok")) != "ok",
            "seed timing",
        )

        self.start_backend()
        first_req_latency = self.wait_backend_ready(timeout_s=60)
        self.log_event("API", "startup", None, first_req_latency, "200", "ok", False, "first request latency /metadata/states")

        stale_running = self.stale_running_count()
        self.log_event("DB", "startup", None, None, "ok", "ok" if stale_running == 0 else "warn", stale_running != 0, "running live runs at boot", {"running_count": stale_running})

        self.login_all_roles()
        self.run_api_audit(startup_mode=True)
        self.explain_query_plan_checks()

        full_boot = os.getenv("BACKEND_MONITOR_FULL_BOOT", "0").strip().lower() in {"1", "true", "yes", "on"}
        if full_boot:
            first_solver = self.trigger_solver_run()
            if first_solver:
                self.monitor_run(first_solver, timeout_s=int(os.getenv("BACKEND_MONITOR_SOLVER_TIMEOUT_SEC", "120")))
            self.rapid_micro_burst()
        else:
            self.log_event(
                "SOLVER",
                "startup",
                None,
                None,
                "skipped",
                "ok",
                False,
                "startup heavy solver checks skipped (set BACKEND_MONITOR_FULL_BOOT=1 to enable)",
            )

        self.write_summary(startup_metrics)

    def run_forever(self, interval_s: int = 20) -> None:
        self.run_once()
        while True:
            try:
                self.run_api_audit()
                self.explain_query_plan_checks()
                self.log_event("DB", "monitor", None, None, "heartbeat", "ok", False, "continuous monitor heartbeat")
            except Exception as exc:
                self.log_event("DB", "monitor", None, None, "exception", "fail", True, f"monitor loop error: {exc}")
            time.sleep(max(5, int(interval_s)))


def main() -> None:
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _acquire_single_instance_lock() -> bool:
        if LOCK_PATH.exists():
            try:
                existing_pid = int((LOCK_PATH.read_text(encoding="utf-8").strip() or "0"))
            except Exception:
                existing_pid = 0
            if _pid_alive(existing_pid):
                return False
            try:
                LOCK_PATH.unlink(missing_ok=True)
            except Exception:
                return False

        try:
            LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            return False

        def _cleanup_lock() -> None:
            try:
                if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    LOCK_PATH.unlink(missing_ok=True)
            except Exception:
                pass

        atexit.register(_cleanup_lock)
        return True

    if not _acquire_single_instance_lock():
        return

    interval = int(os.getenv("BACKEND_MONITOR_INTERVAL_SEC", "20"))
    mode = os.getenv("BACKEND_MONITOR_MODE", "forever").strip().lower()
    monitor = GatewayMonitor()
    if mode == "once":
        monitor.run_once()
    else:
        monitor.run_forever(interval_s=interval)


if __name__ == "__main__":
    main()
