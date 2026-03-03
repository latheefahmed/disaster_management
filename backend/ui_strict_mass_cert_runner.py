from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

import requests
from requests import exceptions as req_exc
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parent
REPORT_JSON = ROOT / "UI_STRICT_MASS_CERT_REPORT.json"
REPORT_MD = ROOT / "UI_STRICT_MASS_CERT_REPORT.md"
PROGRESS_MD = ROOT / "UI_STRICT_MASS_CERT_PROGRESS.md"


@dataclass
class RoleSession:
    role: str
    username: str
    password: str
    token: str
    state_code: str | None
    district_code: str | None


class StrictUIMassRunner:
    def __init__(self) -> None:
        self.frontend_base = os.getenv("UI_STRICT_FRONTEND_BASE", "http://127.0.0.1:5173")
        self.api_base = os.getenv("UI_STRICT_API_BASE", "http://127.0.0.1:8000")
        self.timeout_ms = int(os.getenv("UI_STRICT_TIMEOUT_MS", "30000"))
        self.slow_mo = int(os.getenv("UI_STRICT_SLOW_MO", "40"))
        self.headless = os.getenv("UI_STRICT_HEADLESS", "true").strip().lower() == "true"

        requested_district_runs = int(os.getenv("UI_STRICT_DISTRICT_RUNS", "24"))
        self.min_variant_district_runs = int(os.getenv("UI_STRICT_MIN_VARIANT_RUNS", "40"))
        self.district_runs_target = max(requested_district_runs, self.min_variant_district_runs)
        self.admin_runs_target = int(os.getenv("UI_STRICT_ADMIN_RUNS", "10"))
        self.dashboard_checks_target = int(os.getenv("UI_STRICT_DASHBOARD_CHECKS", "26"))

        self.target_state_code = str(os.getenv("UI_STRICT_STATE_CODE", "33"))
        self.target_district_code = str(os.getenv("UI_STRICT_DISTRICT_CODE", "603"))

        self.role_credentials: dict[str, list[tuple[str, str]]] = {
            "district": [(f"district_{self.target_district_code}", "district123"), (f"district_{self.target_district_code}", "disctrict123")],
            "state": [(f"state_{self.target_state_code}", "state123")],
            "national": [("national_admin", "national123")],
            "admin": [("admin", "admin123"), ("admin_user", "pw"), ("verify_admin", "pw")],
        }

        self.report: dict[str, Any] = {
            "started_at": self.now_iso(),
            "config": {
                "frontend_base": self.frontend_base,
                "api_base": self.api_base,
                "district_runs_requested": requested_district_runs,
                "district_runs_target": self.district_runs_target,
                "admin_runs_target": self.admin_runs_target,
                "dashboard_checks_target": self.dashboard_checks_target,
                "overall_target": self.district_runs_target + self.admin_runs_target + self.dashboard_checks_target,
                "headless": self.headless,
                "slow_mo": self.slow_mo,
            },
            "live_phase": {
                "phase": "init",
                "note": "runner initialized",
                "updated_at": self.now_iso(),
            },
            "district_runs": [],
            "admin_runs": [],
            "dashboard_checks": [],
            "pool_rollup_check": {},
            "auto_escalation_check": {},
            "priority_time_analysis": {},
            "variant_coverage": {},
            "failed_runs": [],
            "errors": [],
        }

        self.sessions: dict[str, RoleSession] = {}

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sleep(seconds: float) -> None:
        time.sleep(max(0.0, float(seconds)))

    def _current_counts(self) -> dict[str, int]:
        district_done = len(self.report.get("district_runs", []))
        admin_done = len(self.report.get("admin_runs", []))
        dashboard_done = len(self.report.get("dashboard_checks", []))
        completed = district_done + admin_done + dashboard_done
        target = int(self.report.get("config", {}).get("overall_target", 0) or 0)
        return {
            "district_done": district_done,
            "admin_done": admin_done,
            "dashboard_done": dashboard_done,
            "completed": completed,
            "remaining": max(0, target - completed),
            "target": target,
            "failed_flagged": len(self.report.get("failed_runs", [])),
        }

    def _write_live_progress(self) -> None:
        counts = self._current_counts()
        phase = self.report.get("live_phase", {}) or {}
        lines = [
            "# UI Strict Mass Certification Live Progress",
            "",
            f"- Updated: {self.now_iso()}",
            f"- Phase: {phase.get('phase', 'unknown')}",
            f"- Note: {phase.get('note', '')}",
            f"- Completed: {counts['completed']} / {counts['target']}",
            f"- Remaining: {counts['remaining']}",
            f"- District runs: {counts['district_done']} / {self.district_runs_target}",
            f"- Admin runs: {counts['admin_done']} / {self.admin_runs_target}",
            f"- Dashboard checks: {counts['dashboard_done']} / {self.dashboard_checks_target}",
            f"- Flagged failed runs: {counts['failed_flagged']}",
            "",
            "## Recent Errors",
        ]

        recent_errors = self.report.get("errors", [])[-8:]
        if recent_errors:
            for err in recent_errors:
                lines.append(f"- [{err.get('stage', 'stage')}] {err.get('error', '')}")
        else:
            lines.append("- none")

        PROGRESS_MD.write_text("\n".join(lines), encoding="utf-8")

    def _set_phase(self, phase: str, note: str = "") -> None:
        self.report["live_phase"] = {
            "phase": str(phase),
            "note": str(note),
            "updated_at": self.now_iso(),
            "counts": self._current_counts(),
        }
        self._write_live_progress()

    def _record_failed(self, block: str, iteration: int, reason: str, details: dict[str, Any] | None = None) -> None:
        self.report.setdefault("failed_runs", []).append(
            {
                "block": block,
                "iteration": int(iteration),
                "reason": str(reason),
                "details": details or {},
                "at": self.now_iso(),
            }
        )

    def _api_login(self, username: str, password: str) -> dict[str, Any]:
        response = requests.post(
            f"{self.api_base}/auth/login",
            json={"username": username, "password": password},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError(f"No token in login response for {username}")
        return payload

    def _api_get(self, role: str, path: str, params: dict[str, Any] | None = None) -> Any:
        token = self.sessions[role].token
        last_err: Exception | None = None
        for attempt in range(1, 5):
            try:
                response = requests.get(
                    f"{self.api_base}{path}",
                    params=params or {},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=40,
                )
                response.raise_for_status()
                return response.json()
            except (req_exc.ReadTimeout, req_exc.ConnectionError) as err:
                last_err = err
                if attempt >= 4:
                    break
                self._sleep(0.5 * attempt)
                continue
            except Exception as err:
                last_err = err
                break

        if last_err is not None:
            raise last_err
        raise RuntimeError(f"GET failed for {path}")

    def _select_code_option(self, select_locator, code: str) -> bool:
        options = select_locator.locator("option")
        total = options.count()
        wanted = str(code).strip()
        for idx in range(total):
            option = options.nth(idx)
            value = (option.get_attribute("value") or "").strip()
            label = (option.inner_text() or "").strip()
            if value == wanted or re.search(rf"\b{re.escape(wanted)}\b", label):
                if value:
                    select_locator.select_option(value=value)
                else:
                    select_locator.select_option(label=label)
                return True
        return False

    def _login_ui(self, page: Page, role: str) -> RoleSession:
        attempts: list[str] = []
        for username, password in self.role_credentials[role]:
            try:
                api_payload: dict[str, Any] | None = None
                try:
                    api_payload = self._api_login(username, password)
                except Exception:
                    attempts.append(f"{username}: api login failed")
                    continue

                page.goto(f"{self.frontend_base}/login", wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.get_by_placeholder(re.compile("username", re.I)).fill(username)
                page.get_by_placeholder(re.compile("password", re.I)).fill(password)

                selects = page.locator("select")
                selects.nth(0).select_option(role)

                if role == "district" and selects.count() > 2:
                    self._select_code_option(selects.nth(1), self.target_state_code)
                    self._select_code_option(selects.nth(2), self.target_district_code)
                elif role == "state" and selects.count() > 1:
                    self._select_code_option(selects.nth(1), self.target_state_code)

                page.get_by_role("button", name=re.compile("login", re.I)).click()

                ok = False
                for _ in range(60):
                    url = str(page.url or "")
                    role_ok = ("/admin" in url) if role == "admin" else bool(re.search(rf"/{role}(?:$|/)", url))
                    if role_ok:
                        token = page.evaluate("() => localStorage.getItem('token')")
                        if token:
                            ok = True
                            break
                    self._sleep(0.2)

                if not ok:
                    try:
                        fallback_user = {
                            "username": username,
                            "role": str(api_payload.get("role") or role),
                            "state_code": api_payload.get("state_code"),
                            "district_code": api_payload.get("district_code"),
                        }
                        fallback_token = str(api_payload.get("access_token") or "")
                        if fallback_token:
                            page.evaluate(
                                """(args) => {
                                    localStorage.setItem('token', args.token)
                                    localStorage.setItem('user', JSON.stringify(args.user))
                                }""",
                                {"token": fallback_token, "user": fallback_user},
                            )
                            page.goto(f"{self.frontend_base}/{role}", wait_until="domcontentloaded", timeout=self.timeout_ms)
                            for _ in range(30):
                                url = str(page.url or "")
                                role_ok = ("/admin" in url) if role == "admin" else bool(re.search(rf"/{role}(?:$|/)", url))
                                token = page.evaluate("() => localStorage.getItem('token')")
                                if role_ok and token:
                                    ok = True
                                    break
                                self._sleep(0.2)
                    except Exception as fallback_err:
                        attempts.append(f"{username}: fallback bootstrap failed: {type(fallback_err).__name__}: {fallback_err}")

                if not ok:
                    err_text = ""
                    try:
                        err_text = (page.locator("text=/Invalid credentials|error/i").first.inner_text(timeout=500) or "").strip()
                    except Exception:
                        err_text = ""
                    suffix = f" error={err_text}" if err_text else ""
                    attempts.append(f"{username}: no redirect/token (url={page.url}){suffix}")
                    continue

                session = RoleSession(
                    role=role,
                    username=username,
                    password=password,
                    token=str(api_payload.get("access_token")),
                    state_code=(None if api_payload.get("state_code") is None else str(api_payload.get("state_code"))),
                    district_code=(None if api_payload.get("district_code") is None else str(api_payload.get("district_code"))),
                )
                return session
            except Exception as err:
                attempts.append(f"{username}: {type(err).__name__}: {err}")
                continue

        raise RuntimeError(f"UI login failed for role={role}; attempts={attempts}")

    def _login_ui_with_retries(self, page: Page, role: str, max_attempts: int = 3) -> RoleSession:
        last_error: Exception | None = None
        for _ in range(max(1, int(max_attempts))):
            try:
                return self._login_ui(page, role)
            except Exception as err:
                last_error = err
                self._sleep(0.8)
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"UI login failed for role={role}")

    def _get_resource_catalog(self) -> list[dict[str, Any]]:
        rows = self._api_get("district", "/metadata/resources")
        return rows if isinstance(rows, list) else []

    def _pick_resource_cycle(self) -> list[dict[str, Any]]:
        catalog = self._get_resource_catalog()
        if not catalog:
            raise RuntimeError("No resources available")

        returnable = [r for r in catalog if bool(r.get("is_returnable"))]
        consumable = [r for r in catalog if bool(r.get("is_consumable"))]

        cycle: list[dict[str, Any]] = []
        if returnable:
            cycle.extend(returnable[:6])
        if consumable:
            cycle.extend(consumable[:6])
        if not cycle:
            cycle = catalog[:12]

        return cycle or catalog[:1]

    def _fill_priority(self, page: Page, priority: int) -> None:
        try:
            page.locator("xpath=//label[contains(normalize-space(), 'Priority')]/following-sibling::input[1]").first.fill(str(int(priority)))
            return
        except Exception:
            pass

        try:
            page.locator("input[aria-label*='Priority'], input[name*='priority' i]").first.fill(str(int(priority)))
        except Exception:
            pass

    def _fill_urgency(self, page: Page, urgency: str) -> None:
        urgency = str(urgency)
        try:
            page.locator("xpath=//label[contains(normalize-space(), 'Urgency')]/following-sibling::select[1]").first.select_option(label=urgency)
            return
        except Exception:
            pass

        try:
            page.locator("select[aria-label*='Urgency'], select[name*='urgency' i]").first.select_option(label=urgency)
        except Exception:
            pass

    def _submit_district_request_ui(self, page: Page, *, resource_id: str, quantity: float, time_index: int, priority: int, urgency: str) -> None:
        page.goto(f"{self.frontend_base}/district/request", wait_until="domcontentloaded", timeout=self.timeout_ms)
        page.mouse.wheel(0, 500)

        resource_select = page.locator("xpath=//label[contains(normalize-space(), 'Resource')]/following-sibling::select[1]").first
        resource_select.select_option(str(resource_id))

        page.locator("xpath=//label[contains(normalize-space(), 'Quantity')]/following-sibling::input[1]").first.fill(str(float(quantity)))
        page.locator("xpath=//label[contains(normalize-space(), 'Time Index')]/following-sibling::input[1]").first.fill(str(int(time_index)))
        self._fill_priority(page, priority)
        self._fill_urgency(page, urgency)

        page.get_by_role("button", name=re.compile("Add to Request Batch", re.I)).click(timeout=5000)
        page.get_by_role("button", name=re.compile("Submit All Requests", re.I)).click(timeout=7000)
        self._sleep(0.8)

    def _run_solver_district_ui(self, page: Page) -> dict[str, Any]:
        before = self._api_get("district", "/district/solver-status")
        before_run_id = before.get("solver_run_id")

        page.goto(f"{self.frontend_base}/district", wait_until="domcontentloaded", timeout=self.timeout_ms)
        page.mouse.wheel(0, 900)
        page.get_by_role("button", name=re.compile("Run Solver|Running Solver", re.I)).first.click(timeout=7000)

        started = time.perf_counter()
        last = before
        while time.perf_counter() - started < 180:
            status = self._api_get("district", "/district/solver-status")
            run_id = status.get("solver_run_id")
            state = str(status.get("status", "")).lower()
            last = status
            if run_id != before_run_id and state == "completed":
                return status
            self._sleep(1.8)

        return last

    def _collect_district_run_evidence(self, run_id: int) -> dict[str, Any]:
        req_rows = self._api_get("district", "/district/requests", params={"page": 1, "page_size": 200})
        alloc_rows = self._api_get("district", "/district/allocations", params={"page": 1, "page_size": 200})
        unmet_rows = self._api_get("district", "/district/unmet", params={"page": 1, "page_size": 200})

        req_rows = [r for r in (req_rows or []) if int(r.get("run_id") or 0) == int(run_id)]
        alloc_rows = [r for r in (alloc_rows or []) if int(r.get("solver_run_id") or 0) == int(run_id)]
        unmet_rows = [r for r in (unmet_rows or []) if int(r.get("solver_run_id") or 0) == int(run_id)]

        demand_total = sum(float(r.get("final_demand_quantity", r.get("quantity", 0)) or 0.0) for r in req_rows)
        allocated_total = sum(float(r.get("allocated_quantity", 0) or 0.0) for r in alloc_rows)
        unmet_total = sum(float(r.get("unmet_quantity", r.get("allocated_quantity", 0)) or 0.0) for r in unmet_rows)
        request_allocated_total = sum(float(r.get("allocated_quantity", 0) or 0.0) for r in req_rows)
        request_unmet_total = sum(float(r.get("unmet_quantity", 0) or 0.0) for r in req_rows)

        districts_allocated = sorted({str(r.get("district_code")) for r in alloc_rows if r.get("district_code") is not None})
        requests_by_district = sorted({str(r.get("district_code")) for r in req_rows if r.get("district_code") is not None})

        return {
            "run_id": int(run_id),
            "request_rows": req_rows,
            "allocation_rows": alloc_rows,
            "unmet_rows": unmet_rows,
            "totals": {
                "demand": demand_total,
                "allocated": allocated_total,
                "unmet": unmet_total,
                "difference_abs": abs((allocated_total + unmet_total) - demand_total),
                "request_allocated": request_allocated_total,
                "request_unmet": request_unmet_total,
                "request_balance_difference_abs": abs((request_allocated_total + request_unmet_total) - demand_total),
            },
            "districts_allocated": districts_allocated,
            "districts_requested": requests_by_district,
        }

    def _build_district_variants(self, resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        urgency_levels = ["Low", "Medium", "High", "Critical"]
        priorities = [1, 2, 3, 4, 5]
        time_indices = list(range(0, 8))
        base_qty_cycle = [20.0, 60.0, 120.0, 300.0, 800.0, 1500.0]

        variants: list[dict[str, Any]] = []
        pick = 0

        def choose_resource() -> dict[str, Any]:
            nonlocal pick
            chosen = resources[pick % len(resources)]
            pick += 1
            return chosen

        for priority, urgency in product(priorities, urgency_levels):
            resource = choose_resource()
            variants.append(
                {
                    "resource": resource,
                    "priority": int(priority),
                    "urgency": str(urgency),
                    "time_index": time_indices[(priority + pick) % len(time_indices)],
                    "base_quantity": base_qty_cycle[pick % len(base_qty_cycle)],
                }
            )

        for time_idx in time_indices:
            resource = choose_resource()
            variants.append(
                {
                    "resource": resource,
                    "priority": priorities[time_idx % len(priorities)],
                    "urgency": urgency_levels[time_idx % len(urgency_levels)],
                    "time_index": int(time_idx),
                    "base_quantity": base_qty_cycle[(time_idx + pick) % len(base_qty_cycle)],
                }
            )

        while len(variants) < self.district_runs_target:
            resource = choose_resource()
            variants.append(
                {
                    "resource": resource,
                    "priority": priorities[pick % len(priorities)],
                    "urgency": urgency_levels[pick % len(urgency_levels)],
                    "time_index": time_indices[pick % len(time_indices)],
                    "base_quantity": base_qty_cycle[pick % len(base_qty_cycle)],
                }
            )

        return variants[: self.district_runs_target]

    def _district_batch(self, page: Page) -> None:
        resources = self._pick_resource_cycle()
        variants = self._build_district_variants(resources)

        for idx, variant in enumerate(variants):
            resource = variant["resource"]
            rid = str(resource.get("resource_id"))
            max_per = float(resource.get("max_per_resource") or 0.0)
            base_qty = float(variant["base_quantity"])
            quantity = min(base_qty, max_per) if max_per > 0 else base_qty
            time_index = int(variant["time_index"])
            priority = int(variant["priority"])
            urgency = str(variant["urgency"])

            started = time.perf_counter()
            status: dict[str, Any] = {}
            run_id = 0
            evidence: dict[str, Any] = {}
            run_pass = False
            run_error: str | None = None

            try:
                self._submit_district_request_ui(
                    page,
                    resource_id=rid,
                    quantity=quantity,
                    time_index=time_index,
                    priority=priority,
                    urgency=urgency,
                )
                status = self._run_solver_district_ui(page)
                run_id = int(status.get("solver_run_id") or 0)
                evidence = self._collect_district_run_evidence(run_id) if run_id > 0 else {}

                run_completed = str(status.get("status", "")).lower() == "completed"
                request_rows = evidence.get("request_rows", []) if isinstance(evidence, dict) else []
                request_balance_diff = float(evidence.get("totals", {}).get("request_balance_difference_abs", 999999.0) or 999999.0)
                run_pass = bool(run_id > 0 and run_completed and len(request_rows) > 0 and request_balance_diff <= 1e-3)
            except Exception as err:
                run_error = f"{type(err).__name__}: {err}"
                self.report["errors"].append({"stage": "district_iteration", "iteration": idx + 1, "error": run_error})

            elapsed_ms = (time.perf_counter() - started) * 1000.0

            record = {
                "test_type": "district_solver_ui",
                "iteration": idx + 1,
                "request_params": {
                    "resource_id": rid,
                    "quantity": quantity,
                    "time_index": time_index,
                    "priority": priority,
                    "urgency": urgency,
                },
                "solver_status": status,
                "elapsed_ms": round(elapsed_ms, 2),
                "evidence": evidence,
                "pass": run_pass,
            }
            if run_error:
                record["error"] = run_error
            self.report["district_runs"].append(record)

            if not run_pass:
                self._record_failed(
                    "district_runs",
                    idx + 1,
                    "district run failed legitimacy checks",
                    {
                        "run_id": run_id,
                        "solver_status": status,
                        "request_rows": len(request_rows),
                        "request_balance_difference_abs": request_balance_diff,
                    },
                )

            self._set_phase("district_batch", f"district run {idx + 1}/{self.district_runs_target}")

            page.goto(f"{self.frontend_base}/district", wait_until="domcontentloaded", timeout=self.timeout_ms)
            for tab_name in ["Requests", "Allocations", "Upstream Supply", "Unmet", "Resource Stocks", "Run History"]:
                try:
                    page.get_by_role("button", name=re.compile(rf"^{re.escape(tab_name)}$", re.I)).first.click(timeout=3000)
                    page.mouse.wheel(0, 900)
                    self._sleep(0.2)
                except Exception:
                    pass

    def _pool_total(self, pool_payload: Any) -> float:
        if isinstance(pool_payload, dict):
            if "total_quantity" in pool_payload:
                return float(pool_payload.get("total_quantity") or 0.0)
            rows = pool_payload.get("rows") or []
            return float(sum(float(r.get("quantity", 0) or 0.0) for r in rows))
        if isinstance(pool_payload, list):
            return float(sum(float(r.get("quantity", 0) or 0.0) for r in pool_payload))
        return 0.0

    def _check_return_rollup_via_ui(self, page: Page) -> None:
        before_state_pool = self._api_get("state", "/state/pool")
        before_national_pool = self._api_get("national", "/national/pool")

        claim_clicked = False
        return_clicked = False

        for _ in range(5):
            page.goto(f"{self.frontend_base}/district", wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.get_by_role("button", name=re.compile("Allocations", re.I)).first.click(timeout=4000)
            except Exception:
                pass
            page.mouse.wheel(0, 1200)

            try:
                claim_buttons = page.get_by_role("button", name=re.compile(r"^Claim$", re.I))
                if claim_buttons.count() > 0:
                    claim_buttons.first.click(timeout=3000)
                    claim_clicked = True
                    self._sleep(0.8)
            except Exception:
                pass

            try:
                confirm_buttons = page.get_by_role("button", name=re.compile(r"^Confirm Received$|^Confirming", re.I))
                if confirm_buttons.count() > 0:
                    confirm_buttons.first.click(timeout=3000)
                    self._sleep(0.8)
            except Exception:
                pass

            try:
                return_buttons = page.get_by_role("button", name=re.compile(r"^Return$", re.I))
                if return_buttons.count() > 0:
                    return_buttons.first.click(timeout=3000)
                    return_clicked = True
                    self._sleep(1.2)
                    break
            except Exception:
                pass

            self._sleep(0.8)

        after_state_pool = self._api_get("state", "/state/pool")
        after_national_pool = self._api_get("national", "/national/pool")

        before_state_total = self._pool_total(before_state_pool)
        after_state_total = self._pool_total(after_state_pool)
        before_national_total = self._pool_total(before_national_pool)
        after_national_total = self._pool_total(after_national_pool)

        pool_pass = bool(return_clicked and ((after_state_total - before_state_total) > 0 or (after_national_total - before_national_total) > 0))

        self.report["pool_rollup_check"] = {
            "claim_clicked": claim_clicked,
            "return_clicked": return_clicked,
            "state_pool_before": before_state_total,
            "state_pool_after": after_state_total,
            "state_pool_delta": after_state_total - before_state_total,
            "national_pool_before": before_national_total,
            "national_pool_after": after_national_total,
            "national_pool_delta": after_national_total - before_national_total,
            "pass": pool_pass,
        }

        if not pool_pass:
            self._record_failed(
                "pool_rollup_check",
                1,
                "return did not increase upstream pools for non-consumable flow",
                {
                    "claim_clicked": claim_clicked,
                    "return_clicked": return_clicked,
                    "state_pool_delta": after_state_total - before_state_total,
                    "national_pool_delta": after_national_total - before_national_total,
                },
            )

        self._set_phase("pool_rollup_check", "validated claim/return -> pool propagation")

    def _find_latest_scenario(self) -> dict[str, Any] | None:
        rows = self._api_get("admin", "/admin/scenarios")
        if not isinstance(rows, list) or not rows:
            return None
        rows_sorted = sorted(rows, key=lambda r: int(r.get("id") or 0), reverse=True)
        return rows_sorted[0]

    def _setup_admin_scenario_ui(self, page: Page) -> int:
        scenario_name = f"strict_ui_mass_{int(time.time())}"
        scenario_id = 0

        page.goto(f"{self.frontend_base}/admin", wait_until="domcontentloaded", timeout=self.timeout_ms)
        page.get_by_placeholder(re.compile("New scenario name", re.I)).fill(scenario_name)
        page.get_by_role("button", name=re.compile("Create Scenario", re.I)).click(timeout=6000)
        self._sleep(2.0)

        latest = self._find_latest_scenario()
        if latest:
            scenario_id = int(latest.get("id") or 0)

        if scenario_id > 0:
            try:
                scenario_select = page.locator("xpath=//label[contains(normalize-space(), 'Selected Scenario')]/following-sibling::select[1]").first
                scenario_select.select_option(value=str(scenario_id))
                self._sleep(0.8)
            except Exception:
                pass

        try:
            page.locator("xpath=//label[contains(normalize-space(), 'Manual')]//input[@type='radio']").first.check(timeout=2000)
        except Exception:
            pass

        try:
            state_select = page.locator("xpath=//label[contains(normalize-space(), 'State')]/following-sibling::select[1]").first
            self._select_code_option(state_select, self.target_state_code)
            self._sleep(0.5)
        except Exception:
            pass

        try:
            district_select = page.locator("xpath=//label[contains(normalize-space(), 'District (Add one at a time)')]/following-sibling::select[1]").first
            if not self._select_code_option(district_select, self.target_district_code):
                options = district_select.locator("option")
                if options.count() > 1:
                    district_select.select_option(index=1)
            self._sleep(0.5)
        except Exception:
            pass

        try:
            checks = page.locator("xpath=//label[contains(normalize-space(), 'Resource Types')]/following-sibling::div[1]//input[@type='checkbox']")
            for idx in range(min(3, checks.count())):
                try:
                    checks.nth(idx).check(timeout=1000)
                except Exception:
                    pass
        except Exception:
            pass

        add_demand_btn = page.get_by_role("button", name=re.compile(r"^Add Demand Batch$", re.I)).first
        enabled = False
        for _ in range(240):
            try:
                if add_demand_btn.is_enabled():
                    enabled = True
                    break
            except Exception:
                pass
            self._sleep(0.25)
        if not enabled:
            raise RuntimeError("Add Demand Batch button not enabled after scenario setup")

        add_demand_btn.click(timeout=10000)
        self._sleep(1.5)

        if scenario_id <= 0:
            latest = self._find_latest_scenario()
            if latest:
                scenario_id = int(latest.get("id") or 0)

        if scenario_id <= 0:
            raise RuntimeError("Unable to resolve created scenario")
        return scenario_id

    def _admin_batch(self, page: Page) -> None:
        scenario_id = self._setup_admin_scenario_ui(page)

        prev_count = 0
        try:
            runs = self._api_get("admin", f"/admin/scenarios/{scenario_id}/runs")
            prev_count = len(runs) if isinstance(runs, list) else 0
        except Exception:
            prev_count = 0

        for idx in range(self.admin_runs_target):
            started = time.perf_counter()
            page.goto(f"{self.frontend_base}/admin", wait_until="domcontentloaded", timeout=self.timeout_ms)

            try:
                page.get_by_role("button", name=re.compile(r"^Solver Runs$", re.I)).first.click(timeout=4000)
            except Exception:
                pass

            try:
                scenario_select = page.locator("xpath=//label[contains(normalize-space(), 'Selected Scenario')]/following-sibling::select[1]").first
                scenario_select.select_option(value=str(scenario_id))
            except Exception:
                pass

            run_btn = page.get_by_role("button", name=re.compile(r"^Run Scenario$|Working", re.I)).first
            finalize_btn = page.get_by_role("button", name=re.compile(r"^Finalize Scenario$", re.I)).first

            ready = False
            for _ in range(120):
                try:
                    if run_btn.is_enabled():
                        ready = True
                        break
                except Exception:
                    pass
                self._sleep(0.25)

            if not ready:
                try:
                    if finalize_btn.is_enabled():
                        finalize_btn.click(timeout=8000)
                        self._sleep(1.5)
                except Exception:
                    pass

            for _ in range(120):
                try:
                    if run_btn.is_enabled():
                        ready = True
                        break
                except Exception:
                    pass
                self._sleep(0.25)

            if not ready:
                raise RuntimeError(f"Run Scenario remained disabled for scenario_id={scenario_id}")

            run_btn.click(timeout=10000)

            current_runs: list[dict[str, Any]] = []
            latest_run_id = 0
            for _ in range(200):
                runs = self._api_get("admin", f"/admin/scenarios/{scenario_id}/runs")
                current_runs = runs if isinstance(runs, list) else []
                if len(current_runs) > prev_count:
                    latest_run_id = int(current_runs[0].get("id") or 0)
                    status = str(current_runs[0].get("status") or "").lower()
                    if status in {"completed", "failed"}:
                        break
                self._sleep(1.0)

            if len(current_runs) > prev_count:
                prev_count = len(current_runs)

            summary = {}
            if latest_run_id > 0:
                try:
                    summary = self._api_get("admin", f"/admin/scenarios/{scenario_id}/runs/{latest_run_id}/summary")
                except Exception as err:
                    self.report["errors"].append({"stage": "admin_summary", "iteration": idx + 1, "error": str(err)})

            elapsed_ms = (time.perf_counter() - started) * 1000.0
            district_breakdown = summary.get("district_breakdown") if isinstance(summary, dict) else []

            self.report["admin_runs"].append(
                {
                    "test_type": "admin_scenario_run_ui",
                    "iteration": idx + 1,
                    "scenario_id": scenario_id,
                    "run_id": latest_run_id,
                    "run_status": (current_runs[0].get("status") if current_runs else None),
                    "elapsed_ms": round(elapsed_ms, 2),
                    "summary": summary,
                    "districts_requested": sorted({str(r.get("district_code")) for r in district_breakdown if r.get("district_code") is not None}),
                    "pass": bool(latest_run_id > 0),
                }
            )

            if latest_run_id <= 0:
                self._record_failed(
                    "admin_runs",
                    idx + 1,
                    "admin run did not produce run_id",
                    {"scenario_id": scenario_id, "run_status": (current_runs[0].get("status") if current_runs else None)},
                )

            self._set_phase("admin_batch", f"admin run {idx + 1}/{self.admin_runs_target}")

            for tab_name in ["Solver Runs", "Neural Controller Status", "Agent Findings", "Audit Logs", "System Health"]:
                try:
                    page.get_by_role("button", name=re.compile(re.escape(tab_name), re.I)).first.click(timeout=3000)
                    page.mouse.wheel(0, 800)
                    self._sleep(0.2)
                except Exception:
                    pass

    def _dashboard_checks(self, state_page: Page, national_page: Page) -> None:
        state_tabs = ["District Requests", "Mutual Aid Outgoing / Incoming", "State Stock", "Refill Resources", "Agent Recommendations", "Run History"]
        national_tabs = ["State Summaries", "National Stock", "Refill Resources", "Inter-State Transfers", "Agent Recommendations", "Run History"]

        for idx in range(self.dashboard_checks_target):
            role = "state" if idx % 2 == 0 else "national"
            page = state_page if role == "state" else national_page
            tab_name = state_tabs[idx % len(state_tabs)] if role == "state" else national_tabs[idx % len(national_tabs)]
            route = "/state" if role == "state" else "/national"

            started = time.perf_counter()
            page.goto(f"{self.frontend_base}{route}", wait_until="domcontentloaded", timeout=self.timeout_ms)

            clicked = True
            try:
                page.get_by_role("button", name=re.compile(re.escape(tab_name), re.I)).first.click(timeout=4000)
                page.mouse.wheel(0, 1000)
                self._sleep(0.3)
            except Exception:
                clicked = False

            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.report["dashboard_checks"].append(
                {
                    "test_type": f"{role}_dashboard_ui",
                    "iteration": idx + 1,
                    "tab": tab_name,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "pass": bool(clicked),
                }
            )

            if not clicked:
                self._record_failed(
                    "dashboard_checks",
                    idx + 1,
                    "dashboard tab click failed",
                    {"role": role, "tab": tab_name},
                )

            self._set_phase("dashboard_checks", f"dashboard check {idx + 1}/{self.dashboard_checks_target}")

    def _auto_escalation_check(self) -> None:
        state_escalations = self._api_get("state", "/state/escalations")
        national_escalations = self._api_get("national", "/national/escalations")

        state_rows = state_escalations if isinstance(state_escalations, list) else []
        national_rows = national_escalations if isinstance(national_escalations, list) else []

        self.report["auto_escalation_check"] = {
            "state_escalations_count": len(state_rows),
            "national_escalations_count": len(national_rows),
            "state_rows_sample": state_rows[:10],
            "national_rows_sample": national_rows[:10],
            "inter_state_sharing_detected": any("transfer" in str(r.get("reason", "")).lower() or "mutual" in str(r.get("reason", "")).lower() for r in (self._api_get("state", "/state/pool/transactions") or [])),
            "pass": bool(len(state_rows) > 0 or len(national_rows) > 0),
        }

    def _priority_time_analysis(self) -> None:
        run_entries = self.report.get("district_runs", [])

        by_priority: dict[int, list[float]] = {}
        by_time: dict[int, list[float]] = {}

        for entry in run_entries:
            req_rows = entry.get("evidence", {}).get("request_rows", []) or []
            for r in req_rows:
                final_demand = float(r.get("final_demand_quantity", r.get("quantity", 0)) or 0.0)
                allocated = float(r.get("allocated_quantity", 0) or 0.0)
                ratio = (allocated / final_demand) if final_demand > 1e-9 else 0.0

                priority = int(r.get("effective_priority") or r.get("priority") or 0)
                time_index = int(r.get("time") or 0)

                if priority > 0:
                    by_priority.setdefault(priority, []).append(ratio)
                by_time.setdefault(time_index, []).append(ratio)

        priority_summary = {
            str(k): {
                "count": len(v),
                "avg_allocation_ratio": (sum(v) / len(v)) if v else 0.0,
            }
            for k, v in sorted(by_priority.items())
        }
        time_summary = {
            str(k): {
                "count": len(v),
                "avg_allocation_ratio": (sum(v) / len(v)) if v else 0.0,
            }
            for k, v in sorted(by_time.items())
        }

        priority_avgs = [x["avg_allocation_ratio"] for x in priority_summary.values()]
        time_avgs = [x["avg_allocation_ratio"] for x in time_summary.values()]

        priority_spread = (max(priority_avgs) - min(priority_avgs)) if len(priority_avgs) >= 2 else 0.0
        time_spread = (max(time_avgs) - min(time_avgs)) if len(time_avgs) >= 2 else 0.0

        self.report["priority_time_analysis"] = {
            "priority_summary": priority_summary,
            "time_summary": time_summary,
            "priority_spread": priority_spread,
            "time_spread": time_spread,
            "priority_significant": bool(priority_spread >= 0.05),
            "time_significant": bool(time_spread >= 0.05),
        }

    def _variant_coverage_analysis(self) -> None:
        district_runs = self.report.get("district_runs", []) or []
        admin_runs = self.report.get("admin_runs", []) or []
        dashboard_checks = self.report.get("dashboard_checks", []) or []

        priorities = sorted({int(r.get("request_params", {}).get("priority") or 0) for r in district_runs if r.get("request_params")})
        urgencies = sorted({str(r.get("request_params", {}).get("urgency") or "") for r in district_runs if r.get("request_params")})
        times = sorted({int(r.get("request_params", {}).get("time_index") or -1) for r in district_runs if r.get("request_params")})
        resources = sorted({str(r.get("request_params", {}).get("resource_id") or "") for r in district_runs if r.get("request_params")})

        expected_priorities = [1, 2, 3, 4, 5]
        expected_urgencies = ["Critical", "High", "Low", "Medium"]
        expected_times = list(range(0, 8))

        state_tabs_expected = {"District Requests", "Mutual Aid Outgoing / Incoming", "State Stock", "Refill Resources", "Agent Recommendations", "Run History"}
        national_tabs_expected = {"State Summaries", "National Stock", "Refill Resources", "Inter-State Transfers", "Agent Recommendations", "Run History"}
        state_tabs_seen = {str(r.get("tab") or "") for r in dashboard_checks if str(r.get("test_type", "")).startswith("state_")}
        national_tabs_seen = {str(r.get("tab") or "") for r in dashboard_checks if str(r.get("test_type", "")).startswith("national_")}

        self.report["variant_coverage"] = {
            "district": {
                "priorities_seen": priorities,
                "urgencies_seen": urgencies,
                "time_indices_seen": times,
                "resource_ids_seen": resources,
                "missing_priorities": [p for p in expected_priorities if p not in priorities],
                "missing_urgencies": [u for u in expected_urgencies if u not in urgencies],
                "missing_time_indices": [t for t in expected_times if t not in times],
            },
            "admin": {
                "runs_executed": len(admin_runs),
                "runs_target": self.admin_runs_target,
            },
            "dashboard": {
                "state_tabs_seen": sorted(state_tabs_seen),
                "state_tabs_missing": sorted(state_tabs_expected - state_tabs_seen),
                "national_tabs_seen": sorted(national_tabs_seen),
                "national_tabs_missing": sorted(national_tabs_expected - national_tabs_seen),
            },
        }

    def _write_reports(self) -> None:
        self.report["finished_at"] = self.now_iso()
        total_tests = len(self.report.get("district_runs", [])) + len(self.report.get("admin_runs", [])) + len(self.report.get("dashboard_checks", []))
        passes = 0
        for block in ("district_runs", "admin_runs", "dashboard_checks"):
            passes += sum(1 for row in self.report.get(block, []) if bool(row.get("pass")))

        self.report["summary"] = {
            "total_tests": total_tests,
            "passed_tests": passes,
            "failed_tests": max(0, total_tests - passes),
            "district_runs": len(self.report.get("district_runs", [])),
            "admin_runs": len(self.report.get("admin_runs", [])),
            "dashboard_checks": len(self.report.get("dashboard_checks", [])),
        }

        REPORT_JSON.write_text(json.dumps(self.report, indent=2), encoding="utf-8")

        md = [
            "# UI Strict Mass Certification Report",
            "",
            f"- Generated: {self.now_iso()}",
            f"- Total tests: {self.report['summary']['total_tests']}",
            f"- Passed: {self.report['summary']['passed_tests']}",
            f"- Failed: {self.report['summary']['failed_tests']}",
            "",
            "## District UI Solver Runs",
            f"- Executed: {len(self.report.get('district_runs', []))}",
            "",
            "## Admin UI Scenario Runs",
            f"- Executed: {len(self.report.get('admin_runs', []))}",
            "",
            "## Dashboard Checks",
            f"- Executed: {len(self.report.get('dashboard_checks', []))}",
            "",
            "## Pool Rollup Check",
            "```json",
            json.dumps(self.report.get("pool_rollup_check", {}), indent=2),
            "```",
            "",
            "## Auto Escalation Check",
            "```json",
            json.dumps(self.report.get("auto_escalation_check", {}), indent=2),
            "```",
            "",
            "## Priority/Time Analysis",
            "```json",
            json.dumps(self.report.get("priority_time_analysis", {}), indent=2),
            "```",
            "",
            "## Variant Coverage",
            "```json",
            json.dumps(self.report.get("variant_coverage", {}), indent=2),
            "```",
            "",
            "## Failed Runs (Flagged)",
            f"- Count: {len(self.report.get('failed_runs', []))}",
            "```json",
            json.dumps(self.report.get("failed_runs", [])[-50:], indent=2),
            "```",
            "",
            "## Full Results",
            f"- JSON: {REPORT_JSON.name}",
        ]

        REPORT_MD.write_text("\n".join(md), encoding="utf-8")

    def run(self) -> int:
        started = time.perf_counter()
        self._set_phase("startup", "launching playwright and contexts")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, slow_mo=self.slow_mo)

            district_ctx = browser.new_context(viewport={"width": 1600, "height": 920})
            state_ctx = browser.new_context(viewport={"width": 1600, "height": 920})
            national_ctx = browser.new_context(viewport={"width": 1600, "height": 920})
            admin_ctx = browser.new_context(viewport={"width": 1600, "height": 920})

            district_page = district_ctx.new_page()
            state_page = state_ctx.new_page()
            national_page = national_ctx.new_page()
            admin_page = admin_ctx.new_page()

            for page in (district_page, state_page, national_page, admin_page):
                page.set_default_timeout(self.timeout_ms)

            self._set_phase("login", "logging in district/state/national/admin")
            self.sessions["district"] = self._login_ui_with_retries(district_page, "district")
            self.sessions["state"] = self._login_ui_with_retries(state_page, "state")
            self.sessions["national"] = self._login_ui_with_retries(national_page, "national")
            try:
                self.sessions["admin"] = self._login_ui_with_retries(admin_page, "admin")
            except Exception:
                try:
                    admin_ctx.close()
                except Exception:
                    pass
                admin_ctx = browser.new_context(viewport={"width": 1600, "height": 920})
                admin_page = admin_ctx.new_page()
                admin_page.set_default_timeout(self.timeout_ms)
                self.sessions["admin"] = self._login_ui_with_retries(admin_page, "admin")

            self._set_phase("district_batch", "executing district request+solver variants")
            self._district_batch(district_page)
            self._set_phase("pool_rollup_check", "checking claim/return rollup into pools")
            self._check_return_rollup_via_ui(district_page)
            self._set_phase("admin_batch", "executing admin scenario runs")
            self._admin_batch(admin_page)
            self._set_phase("dashboard_checks", "executing state/national dashboard tab checks")
            self._dashboard_checks(state_page, national_page)
            self._set_phase("post_checks", "running escalation + model effectiveness analyses")
            self._auto_escalation_check()
            self._priority_time_analysis()
            self._variant_coverage_analysis()

            district_ctx.close()
            state_ctx.close()
            national_ctx.close()
            admin_ctx.close()
            browser.close()

        self.report["duration_seconds"] = round(time.perf_counter() - started, 2)
        self._set_phase("finalizing", "writing final reports")
        self._write_reports()
        self._set_phase("completed", "run completed")

        summary = self.report.get("summary", {})
        return 0 if int(summary.get("failed_tests", 0)) == 0 else 1


def main() -> None:
    runner = StrictUIMassRunner()
    exit_code = 1
    try:
        exit_code = runner.run()
    except PlaywrightTimeoutError as err:
        runner.report["errors"].append({"stage": "playwright_timeout", "error": str(err)})
        runner._write_reports()
        exit_code = 1
    except Exception as err:
        runner.report["errors"].append({"stage": "fatal", "error": str(err)})
        runner._write_reports()
        exit_code = 1

    print(f"JSON report: {REPORT_JSON}")
    print(f"Markdown report: {REPORT_MD}")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
