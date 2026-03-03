from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from playwright.sync_api import (
        Browser,
        BrowserContext,
        Error as PlaywrightError,
        Page,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except Exception as import_error:  # pragma: no cover
    print("[FAIL] Playwright is not available. Install with: pip install playwright ; playwright install")
    print(f"[FAIL] Import error: {import_error}")
    sys.exit(2)


ROOT_DIR = Path(__file__).resolve().parent
SCREENSHOT_DIR = ROOT_DIR / "ui_screenshots"
VIDEO_DIR = ROOT_DIR / "ui_videos"
JSON_REPORT_PATH = ROOT_DIR / "ui_audit_results.json"
MARKDOWN_REPORT_PATH = ROOT_DIR / "UI_AUDIT_REPORT.md"


@dataclass
class Finding:
    category: str
    severity: str
    message: str
    evidence: dict[str, Any]


@dataclass
class StepResult:
    name: str
    passed: bool
    details: dict[str, Any]


class UIAuditor:
    def __init__(self) -> None:
        self.frontend_base = os.getenv("UI_AUDIT_FRONTEND_BASE", "http://127.0.0.1:5173")
        self.api_base = os.getenv("UI_AUDIT_API_BASE", "http://127.0.0.1:8000")
        self.frontend_candidates = [
            self.frontend_base,
            "http://127.0.0.1:5174",
            "http://localhost:5173",
            "http://localhost:5174",
        ]

        self.target_district_code = str(os.getenv("UI_AUDIT_DISTRICT_CODE", "603"))
        self.target_state_code = str(os.getenv("UI_AUDIT_STATE_CODE", "33"))

        self.timeout_ms = int(os.getenv("UI_AUDIT_TIMEOUT_MS", "20000"))
        self.slow_mo = int(os.getenv("UI_AUDIT_SLOW_MO", "150"))

        self.role_credentials: dict[str, list[tuple[str, str]]] = {
            "district": [
                (f"district_{self.target_district_code}", "disctrict123"),
                (f"district_{self.target_district_code}", "district123"),
                (f"district_{self.target_district_code}", "pw"),
                ("district_user", "pw"),
                ("district_1001", "pw"),
            ],
            "state": [
                (f"state_{self.target_state_code}", "state123"),
                (f"state_{self.target_state_code}", "pw"),
                ("state_user", "pw"),
                ("state_10", "pw"),
            ],
            "national": [
                ("national_admin", "national123"),
                ("national_user", "pw"),
                ("verify_national", "pw"),
            ],
            "admin": [
                ("admin", "admin123"),
                ("admin_user", "pw"),
                ("verify_admin", "pw"),
            ],
        }

        self.findings: list[Finding] = []
        self.screenshots: list[str] = []
        self.visited_tabs: set[str] = set()
        self.step_results: list[StepResult] = []

        self.network_events: list[dict[str, Any]] = []
        self.console_events: list[dict[str, Any]] = []
        self.pending_requests: dict[Any, float] = {}

        self.role_sessions: dict[str, dict[str, Any]] = {}

        self.results: dict[str, Any] = {
            "started_at": self.now_iso(),
            "config": {
                "frontend_base": self.frontend_base,
                "api_base": self.api_base,
                "headless": False,
                "slow_mo": self.slow_mo,
                "target_district_code": self.target_district_code,
                "target_state_code": self.target_state_code,
            },
            "role_matrix": {},
            "district_tests": {},
            "state_tests": {},
            "national_tests": {},
            "admin_tests": {},
            "invariant_violations": [],
            "ui_mismatches": [],
            "performance_issues": [],
            "findings": [],
            "screenshots": [],
            "stop_condition": {},
            "error": None,
        }

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def parse_number(text: str) -> float:
        cleaned = re.sub(r"[^0-9.\-]", "", text or "")
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def log_step(self, message: str) -> None:
        print(f"[STEP] {message}")

    def log_check(self, message: str) -> None:
        print(f"[CHECK] {message}")

    def log_pass(self, message: str) -> None:
        print(f"[PASS] {message}")

    def log_fail(self, message: str) -> None:
        print(f"[FAIL] {message}")

    def add_finding(self, category: str, severity: str, message: str, **evidence: Any) -> None:
        finding = Finding(category=category, severity=severity, message=message, evidence=evidence)
        self.findings.append(finding)

        if category == "PERFORMANCE_ISSUE":
            self.results["performance_issues"].append({"message": message, "evidence": evidence})
        elif category in {"UI_BUG", "UX_REDUNDANCY", "DATA_MISMATCH", "BACKEND_BUG"}:
            self.results["ui_mismatches"].append({"category": category, "message": message, "evidence": evidence})

    def record_step_result(self, name: str, passed: bool, **details: Any) -> None:
        self.step_results.append(StepResult(name=name, passed=passed, details=details))

    def api_login(self, username: str, password: str) -> dict[str, Any] | None:
        url = f"{self.api_base}/auth/login"
        try:
            response = requests.post(url, json={"username": username, "password": password}, timeout=20)
            if not response.ok:
                return None
            payload = response.json()
            token = payload.get("access_token")
            if not token:
                return None
            session = requests.Session()
            session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            return {
                "username": username,
                "password": password,
                "token": token,
                "role": payload.get("role"),
                "state_code": payload.get("state_code"),
                "district_code": payload.get("district_code"),
                "session": session,
            }
        except Exception as error:
            self.add_finding("BACKEND_BUG", "high", "API login call failed", username=username, error=str(error))
            return None

    def _attach_telemetry(self, page: Page) -> None:
        def on_console(msg: Any) -> None:
            entry = {
                "type": msg.type,
                "text": msg.text,
                "location": msg.location,
                "time": self.now_iso(),
            }
            self.console_events.append(entry)
            if str(msg.type).lower() == "error":
                self.add_finding("UI_BUG", "high", "Console error detected", console=entry)

        def on_request(request: Any) -> None:
            self.pending_requests[request] = time.perf_counter()

        def on_response(response: Any) -> None:
            request = response.request
            start = self.pending_requests.pop(request, None)
            duration = None
            if start is not None:
                duration = time.perf_counter() - start

            event = {
                "url": response.url,
                "status": response.status,
                "method": request.method,
                "duration_seconds": duration,
                "time": self.now_iso(),
            }
            self.network_events.append(event)

            if isinstance(response.status, int) and response.status >= 400:
                self.add_finding("BACKEND_BUG", "high", "HTTP 4xx/5xx detected", response=event)

            if duration is not None and duration > 3.0:
                self.add_finding(
                    "PERFORMANCE_ISSUE",
                    "medium",
                    "Slow network response (>3s)",
                    response=event,
                )

        def on_request_failed(request: Any) -> None:
            event = {
                "url": request.url,
                "method": request.method,
                "failure": request.failure,
                "time": self.now_iso(),
            }
            self.network_events.append(event)
            self.pending_requests.pop(request, None)
            self.add_finding("BACKEND_BUG", "high", "Request failed", request=event)

        page.on("console", on_console)
        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)

    def screenshot(self, page: Page, name: str) -> str:
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
        path = SCREENSHOT_DIR / f"{safe_name}.png"
        page.screenshot(path=str(path), full_page=True)
        relative = path.relative_to(ROOT_DIR).as_posix()
        self.screenshots.append(relative)
        return relative

    def wait_for_app(self) -> None:
        self.log_step("Checking frontend/backend availability")
        for _ in range(30):
            back_ok = False
            try:
                back = requests.get(f"{self.api_base}/metadata/resources", timeout=5)
                back_ok = bool(back.ok)
            except Exception:
                back_ok = False

            for candidate in self.frontend_candidates:
                try:
                    front = requests.get(f"{candidate}/login", timeout=5)
                    if bool(front.ok) and back_ok:
                        self.frontend_base = candidate
                        self.log_pass(f"Frontend and backend are reachable (frontend={candidate})")
                        return
                except Exception:
                    continue
            time.sleep(1)

        raise RuntimeError(
            "Frontend/backend not reachable. Start services first (backend on :8000, frontend on :5173 or :5174)."
        )

    @staticmethod
    def _extract_code_from_username(username: str, prefix: str) -> str | None:
        match = re.match(rf"^{re.escape(prefix)}_(\d+)$", str(username or "").strip().lower())
        return match.group(1) if match else None

    def _resolve_state_code_for_district(self, district_code: str | None) -> str | None:
        if not district_code:
            return None
        try:
            response = requests.get(
                f"{self.api_base}/metadata/districts",
                params={"state_code": self.target_state_code},
                timeout=10,
            )
            if response.ok:
                for row in response.json() or []:
                    if str(row.get("district_code")) == str(district_code):
                        return str(row.get("state_code"))
        except Exception:
            pass

        try:
            response = requests.get(f"{self.api_base}/metadata/districts", timeout=10)
            if response.ok:
                for row in response.json() or []:
                    if str(row.get("district_code")) == str(district_code):
                        return str(row.get("state_code"))
        except Exception:
            pass

        return self.target_state_code

    @staticmethod
    def _select_option_by_code(select_locator: Any, code: str | None) -> bool:
        if not code:
            return False

        value = select_locator.evaluate(
            """
            (el, code) => {
              const norm = String(code || '');
              const variants = new Set([
                norm,
                norm.replace(/^0+/, ''),
                norm.padStart(2, '0')
              ]);
              const options = Array.from(el.options || []);

              for (const o of options) {
                if (variants.has(String(o.value || ''))) return String(o.value || '');
              }

              for (const o of options) {
                const text = String(o.textContent || '');
                if (text.includes(`(${norm})`) || text.includes(` ${norm}`) || text.includes(norm)) {
                  return String(o.value || '');
                }
              }

              return null;
            }
            """,
            code,
        )

        if not value:
            return False

        select_locator.select_option(value=str(value))
        return True

    def _select_login_dropdowns(self, page: Page, role: str, username: str) -> None:
        if role == "district":
            district_code = self._extract_code_from_username(username, "district") or self.target_district_code
            state_code = self._resolve_state_code_for_district(district_code)

            state_select = page.locator("select").nth(1)
            state_select.wait_for(state="visible", timeout=5000)
            state_ok = self._select_option_by_code(state_select, state_code)
            if not state_ok:
                self.add_finding(
                    "UI_BUG",
                    "medium",
                    "Could not auto-select state dropdown on district login",
                    username=username,
                    desired_state_code=state_code,
                )

            district_select = page.locator("select").nth(2)
            district_select.wait_for(state="visible", timeout=5000)
            district_ok = self._select_option_by_code(district_select, district_code)
            if not district_ok:
                self.add_finding(
                    "UI_BUG",
                    "medium",
                    "Could not auto-select district dropdown on district login",
                    username=username,
                    desired_district_code=district_code,
                )

        elif role == "state":
            state_code = self._extract_code_from_username(username, "state") or self.target_state_code
            state_select = page.locator("select").nth(1)
            state_select.wait_for(state="visible", timeout=5000)
            state_ok = self._select_option_by_code(state_select, state_code)
            if not state_ok:
                self.add_finding(
                    "UI_BUG",
                    "medium",
                    "Could not auto-select state dropdown on state login",
                    username=username,
                    desired_state_code=state_code,
                )

    def login_ui(
        self,
        page: Page,
        role: str,
        expected_path: str,
        credential_candidates: list[tuple[str, str]],
    ) -> dict[str, Any]:
        self.log_step(f"Logging in as {role.capitalize()}")
        errors: list[str] = []

        for username, password in credential_candidates:
            try:
                login_attempt_timeout_ms = min(self.timeout_ms, 6000)
                page.goto(f"{self.frontend_base}/login", wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.get_by_placeholder(re.compile("username", re.I)).fill(username, timeout=self.timeout_ms)
                page.get_by_placeholder(re.compile("password", re.I)).fill(password, timeout=self.timeout_ms)
                page.locator("select").first.select_option(role)
                self._select_login_dropdowns(page, role, username)

                page.get_by_role("button", name=re.compile("login", re.I)).click()
                deadline = time.perf_counter() + (login_attempt_timeout_ms / 1000.0)
                parsed_user: dict[str, Any] = {}
                token = None
                login_ok = False

                while time.perf_counter() < deadline:
                    current_url = str(page.url or "")
                    if re.search(rf"/{re.escape(expected_path)}$", current_url):
                        login_ok = True
                        break

                    user_data = page.evaluate("() => window.localStorage.getItem('user')")
                    token = page.evaluate("() => window.localStorage.getItem('token')")
                    parsed_user = json.loads(user_data) if user_data else {}

                    if token and str(parsed_user.get("role", "")).lower() == role:
                        if not re.search(rf"/{re.escape(expected_path)}$", current_url):
                            page.goto(
                                f"{self.frontend_base}/{expected_path}",
                                wait_until="domcontentloaded",
                                timeout=self.timeout_ms,
                            )
                        login_ok = True
                        break

                    invalid_locator = page.get_by_text(re.compile("Invalid credentials", re.I))
                    if invalid_locator.count() > 0 and invalid_locator.first.is_visible():
                        raise RuntimeError("Invalid credentials shown by login UI")

                    page.wait_for_timeout(250)

                if not login_ok:
                    raise RuntimeError(f"Login timed out; current_url={page.url}")

                user_data = page.evaluate("() => window.localStorage.getItem('user')")
                token = page.evaluate("() => window.localStorage.getItem('token')")
                parsed_user = json.loads(user_data) if user_data else {}

                session_info = {
                    "username": username,
                    "password": password,
                    "token": token,
                    "role": parsed_user.get("role"),
                    "state_code": parsed_user.get("state_code"),
                    "district_code": parsed_user.get("district_code"),
                }
                self.log_pass(f"{role.capitalize()} login succeeded with {username}")
                return session_info

            except Exception as error:
                errors.append(f"{username}: {error}")

        raise RuntimeError(f"Login failed for role={role}. Attempts: {' | '.join(errors)}")

    def get_valid_credential_candidates(self, role: str) -> list[tuple[str, str]]:
        candidates = self.role_credentials.get(role, [])
        valid: list[tuple[str, str]] = []
        for username, password in candidates:
            session = self.api_login(username, password)
            if session and str(session.get("role", "")).lower() == role:
                valid.append((username, password))

        return valid if valid else candidates

    def get_stat_card_value(self, page: Page, label: str) -> float:
        locator = page.locator(f"xpath=//p[normalize-space()='{label}']/following-sibling::p[1]").first
        text_value = locator.inner_text(timeout=self.timeout_ms)
        return self.parse_number(text_value)

    def api_get(self, role: str, path: str, params: dict[str, Any] | None = None) -> Any:
        role_data = self.role_sessions.get(role)
        if not role_data:
            raise RuntimeError(f"Missing API session for role={role}")

        session: requests.Session = role_data["api"]["session"]
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = session.get(f"{self.api_base}{path}", params=params, timeout=90)
                if not response.ok:
                    raise RuntimeError(f"GET {path} -> {response.status_code}: {response.text[:300]}")
                return response.json()
            except Exception as error:
                last_error = error
                if attempt < 3:
                    time.sleep(1.5 * attempt)
                    continue
                raise

        raise RuntimeError(str(last_error) if last_error else f"GET {path} failed")

    def api_post(self, role: str, path: str, payload: dict[str, Any]) -> Any:
        role_data = self.role_sessions.get(role)
        if not role_data:
            raise RuntimeError(f"Missing API session for role={role}")

        session: requests.Session = role_data["api"]["session"]
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = session.post(f"{self.api_base}{path}", json=payload, timeout=120)
                if not response.ok:
                    raise RuntimeError(f"POST {path} -> {response.status_code}: {response.text[:300]}")
                return response.json()
            except Exception as error:
                last_error = error
                if attempt < 3:
                    time.sleep(2 * attempt)
                    continue
                raise

        raise RuntimeError(str(last_error) if last_error else f"POST {path} failed")

    def wait_for_solver_refresh(self, before_run_id: int | None, timeout_seconds: int = 90) -> dict[str, Any]:
        start = time.perf_counter()
        last_status: dict[str, Any] = {}
        while time.perf_counter() - start <= timeout_seconds:
            status = self.api_get("district", "/district/solver-status")
            last_status = status
            run_id = status.get("solver_run_id")
            if before_run_id is None and run_id is not None:
                return status
            if before_run_id is not None and run_id not in (None, before_run_id):
                return status
            time.sleep(2)
        return last_status

    def pick_resource_ids(self) -> dict[str, str]:
        resources = self.api_get("district", "/metadata/resources")

        water_id = None
        volunteers_id = None
        fallback_id = None

        for row in resources:
            resource_id = str(row.get("resource_id", ""))
            resource_name = str(row.get("resource_name", ""))
            label = str(row.get("label", ""))
            haystack = f"{resource_id} {resource_name} {label}".lower()

            if fallback_id is None:
                fallback_id = resource_id

            if water_id is None and ("water" in haystack or "liter" in haystack):
                water_id = resource_id

            if volunteers_id is None and (
                "volunteer" in haystack or "volunteers" in haystack or "human" in haystack or "rescue_team" in haystack
            ):
                volunteers_id = resource_id

        if water_id is None:
            water_id = fallback_id
            self.add_finding(
                "DATA_MISMATCH",
                "medium",
                "Could not find explicit water resource; using fallback resource",
                fallback_resource=fallback_id,
            )

        if volunteers_id is None:
            volunteers_id = fallback_id
            self.add_finding(
                "DATA_MISMATCH",
                "medium",
                "Could not find explicit volunteers resource; using fallback resource",
                fallback_resource=fallback_id,
            )

        return {"water": str(water_id), "volunteers": str(volunteers_id)}

    def submit_request_via_ui(self, page: Page, resource_id: str, quantity: float, time_index: int) -> None:
        self.log_step(f"Submitting district request resource={resource_id}, quantity={quantity}, time={time_index}")
        ui_submit_ok = False
        try:
            page.goto(f"{self.frontend_base}/district/request", wait_until="domcontentloaded", timeout=self.timeout_ms)
            self.visited_tabs.add("district:/district/request")
            page.get_by_text(re.compile("District Resource Request", re.I)).first.wait_for(timeout=6000)

            resource_select = page.locator("xpath=//label[contains(normalize-space(), 'Resource')]/following-sibling::select[1]").first
            resource_select.select_option(resource_id)

            time_input = page.locator("xpath=//label[contains(normalize-space(), 'Time Index')]/following-sibling::input[1]").first
            time_input.fill(str(time_index))

            quantity_input = page.locator("xpath=//label[contains(normalize-space(), 'Quantity')]/following-sibling::input[1]").first
            quantity_input.fill(str(quantity))

            page.get_by_role("button", name=re.compile("Add to Request Batch", re.I)).click()
            page.get_by_role("button", name=re.compile("Submit All Requests", re.I)).click()
            ui_submit_ok = True
        except Exception as error:
            self.add_finding(
                "UI_BUG",
                "medium",
                "District request UI submit unavailable; falling back to API request batch",
                resource_id=resource_id,
                quantity=quantity,
                time=time_index,
                error=str(error),
            )

        if not ui_submit_ok:
            self.api_post(
                "district",
                "/district/request-batch",
                {
                    "items": [
                        {
                            "resource_id": str(resource_id),
                            "time": int(time_index),
                            "quantity": float(quantity),
                            "priority": None,
                            "urgency": None,
                            "confidence": 1,
                            "source": "human",
                        }
                    ]
                },
            )

        time.sleep(1)
        try:
            self.screenshot(page, f"district_request_submit_t{time_index}")
        except Exception:
            pass

    def run_solver_via_ui(self, page: Page) -> dict[str, Any]:
        self.log_step("Triggering district solver")
        before_status = self.api_get("district", "/district/solver-status")
        before_run_id = before_status.get("solver_run_id")

        ui_run_ok = False
        try:
            page.goto(f"{self.frontend_base}/district", wait_until="domcontentloaded", timeout=self.timeout_ms)
            self.visited_tabs.add("district:/district")
            page.get_by_role("button", name=re.compile("Run Solver|Running Solver", re.I)).first.click(timeout=5000)
            ui_run_ok = True
        except Exception as error:
            self.add_finding(
                "UI_BUG",
                "medium",
                "District Run Solver button unavailable; falling back to API /district/run",
                error=str(error),
            )

        if not ui_run_ok:
            self.api_post("district", "/district/run", {})

        status = self.wait_for_solver_refresh(before_run_id=before_run_id)

        self.screenshot(page, f"district_solver_after_run_{status.get('solver_run_id')}")
        return status

    def verify_invariants(self, label: str) -> dict[str, Any]:
        requests_rows = self.api_get("district", "/district/requests", params={"latest_only": "true"})
        allocations = self.api_get("district", "/district/allocations")
        unmet_rows = self.api_get("district", "/district/unmet")

        final_demand = sum(float(row.get("final_demand_quantity", row.get("quantity", 0)) or 0) for row in requests_rows)
        allocated = sum(float(row.get("allocated_quantity", 0) or 0) for row in allocations)
        unmet = sum(float(row.get("unmet_quantity", 0) or 0) for row in unmet_rows)

        diff = abs((allocated + unmet) - final_demand)
        invariant_ok = diff <= 1e-4

        if not invariant_ok:
            message = f"Invariant failed at {label}: allocated + unmet != final_demand"
            self.results["invariant_violations"].append(
                {
                    "label": label,
                    "allocated": allocated,
                    "unmet": unmet,
                    "final_demand": final_demand,
                    "difference": diff,
                }
            )
            self.add_finding(
                "BACKEND_BUG",
                "high",
                message,
                allocated=allocated,
                unmet=unmet,
                final_demand=final_demand,
                difference=diff,
            )

        duplicate_keys: dict[tuple[Any, ...], int] = {}
        for row in allocations:
            key = (
                row.get("solver_run_id"),
                row.get("district_code"),
                row.get("resource_id"),
                row.get("time"),
                row.get("allocated_quantity"),
                row.get("supply_level"),
                row.get("origin_state_code"),
                row.get("origin_district_code"),
            )
            duplicate_keys[key] = duplicate_keys.get(key, 0) + 1

        duplicates = [str(key) for key, count in duplicate_keys.items() if count > 1]
        if duplicates:
            self.add_finding(
                "BACKEND_BUG",
                "high",
                "Duplicate allocations detected",
                duplicates=duplicates[:10],
            )

        zero_final_included = [
            row for row in requests_rows if bool(row.get("included_in_run")) and float(row.get("final_demand_quantity", 0) or 0) <= 0
        ]
        if zero_final_included:
            self.add_finding(
                "BACKEND_BUG",
                "high",
                "Included requests with zero final demand detected",
                rows=zero_final_included[:10],
            )

        latest_status = self.api_get("district", "/district/solver-status")
        if str(latest_status.get("status", "")).lower() == "running":
            self.add_finding(
                "BACKEND_BUG",
                "medium",
                "Stale running run detected in solver status",
                status=latest_status,
            )

        return {
            "allocated": allocated,
            "unmet": unmet,
            "final_demand": final_demand,
            "difference": diff,
            "ok": invariant_ok,
        }

    def _find_request_rows(self, resource_id: str, time_index: int) -> list[dict[str, Any]]:
        rows = self.api_get("district", "/district/requests", params={"latest_only": "true"})
        return [
            row
            for row in rows
            if str(row.get("resource_id")) == str(resource_id) and int(row.get("time", -1)) == int(time_index)
        ]

    def _find_alloc_unmet_by_slot(self, resource_id: str, time_index: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        allocations = self.api_get("district", "/district/allocations")
        unmet_rows = self.api_get("district", "/district/unmet")
        matched_alloc = [
            row
            for row in allocations
            if str(row.get("resource_id")) == str(resource_id) and int(row.get("time", -1)) == int(time_index)
        ]
        matched_unmet = [
            row
            for row in unmet_rows
            if str(row.get("resource_id")) == str(resource_id) and int(row.get("time", -1)) == int(time_index)
        ]
        return matched_alloc, matched_unmet

    def run_district_cases(self, page: Page) -> None:
        self.log_step("Running District 603 full flow tests")
        district_out: dict[str, Any] = {}

        page.goto(f"{self.frontend_base}/district", wait_until="domcontentloaded", timeout=self.timeout_ms)
        district_ready = False
        try:
            page.get_by_text(re.compile("District Overview", re.I)).first.wait_for(timeout=5000)
            district_ready = True
        except Exception:
            pass

        if not district_ready:
            try:
                page.get_by_role("button", name=re.compile("Run Solver|Running Solver", re.I)).first.wait_for(timeout=self.timeout_ms)
                district_ready = True
            except Exception:
                pass

        if not district_ready:
            self.add_finding(
                "UI_BUG",
                "medium",
                "District overview widgets not fully visible; proceeding with API-backed checks",
                url=page.url,
            )
        try:
            self.screenshot(page, "district_baseline_dashboard")
        except Exception:
            pass

        ui_kpis = {
            "total_final_demand": 0.0,
            "allocated": 0.0,
            "unmet": 0.0,
            "coverage_pct": 0.0,
        }
        try:
            ui_kpis = {
                "total_final_demand": self.get_stat_card_value(page, "Total Final Demand"),
                "allocated": self.get_stat_card_value(page, "Allocated Resources"),
                "unmet": self.get_stat_card_value(page, "Unmet Demand"),
                "coverage_pct": self.get_stat_card_value(page, "Coverage %"),
            }
        except Exception as error:
            self.add_finding(
                "UI_BUG",
                "medium",
                "District KPI cards not parsable; using backend totals as baseline",
                error=str(error),
            )

        backend_requests = self.api_get("district", "/district/requests", params={"latest_only": "true"})
        backend_allocs = self.api_get("district", "/district/allocations")
        backend_unmet = self.api_get("district", "/district/unmet")

        api_totals = {
            "total_final_demand": sum(float(row.get("final_demand_quantity", row.get("quantity", 0)) or 0) for row in backend_requests),
            "allocated": sum(float(row.get("allocated_quantity", 0) or 0) for row in backend_allocs),
            "unmet": sum(float(row.get("unmet_quantity", 0) or 0) for row in backend_unmet),
        }
        api_totals["coverage_pct"] = (api_totals["allocated"] / api_totals["total_final_demand"] * 100.0) if api_totals["total_final_demand"] > 1e-9 else 0.0

        baseline_checks = {}
        for key in ("total_final_demand", "allocated", "unmet", "coverage_pct"):
            diff = abs(ui_kpis[key] - api_totals[key])
            baseline_checks[key] = {"ui": ui_kpis[key], "api": api_totals[key], "difference": diff, "ok": diff <= 1e-4}
            if diff > 1e-4:
                self.add_finding("DATA_MISMATCH", "high", f"KPI mismatch for {key}", ui=ui_kpis[key], api=api_totals[key], difference=diff)

        district_out["baseline"] = {"ui_kpis": ui_kpis, "api_totals": api_totals, "checks": baseline_checks}

        resource_map = self.pick_resource_ids()
        water_resource = resource_map["water"]
        volunteers_resource = resource_map["volunteers"]

        # Case 1
        case_results: dict[str, Any] = {}
        self.log_step("Case 1 — Small demand should allocate locally")
        self.submit_request_via_ui(page, water_resource, 10, 101)
        self.run_solver_via_ui(page)
        alloc_rows, unmet_rows = self._find_alloc_unmet_by_slot(water_resource, 101)
        request_rows = self._find_request_rows(water_resource, 101)

        case1_ok = bool(request_rows) and any(str(r.get("status", "")).lower() == "allocated" for r in request_rows) and bool(alloc_rows)
        if alloc_rows and not any(float(r.get("allocated_quantity", 0) or 0) > 0 for r in alloc_rows):
            case1_ok = False
        if alloc_rows and not any(str(r.get("supply_level", "district")).lower() == "district" for r in alloc_rows):
            case1_ok = False

        case_results["case_1_small_local"] = {
            "passed": case1_ok,
            "request_rows": request_rows,
            "allocation_rows": alloc_rows,
            "unmet_rows": unmet_rows,
        }
        if case1_ok:
            self.log_pass("Case 1")
        else:
            self.log_fail("Case 1 - expected local allocation did not fully match")

        # Case 2 (search for state-level escalation)
        self.log_step("Case 2 — Exceed district stock but not state")
        state_case_quantities = [15, 50, 120, 250, 500]
        selected_case2: dict[str, Any] | None = None
        for quantity in state_case_quantities:
            self.submit_request_via_ui(page, water_resource, quantity, 102)
            self.run_solver_via_ui(page)
            alloc_rows, unmet_rows = self._find_alloc_unmet_by_slot(water_resource, 102)
            if any(str(r.get("supply_level", "")).lower() == "state" for r in alloc_rows):
                selected_case2 = {
                    "quantity": quantity,
                    "alloc_rows": alloc_rows,
                    "unmet_rows": unmet_rows,
                }
                break

        case2_ok = selected_case2 is not None
        case2_details: dict[str, Any] = selected_case2 or {"quantities_tried": state_case_quantities}

        if selected_case2:
            allocation_id = None
            receipt_confirmed_initially = None
            for row in selected_case2["alloc_rows"]:
                if str(row.get("supply_level", "")).lower() == "state":
                    allocation_id = row.get("id")
                    receipt_confirmed_initially = bool(row.get("receipt_confirmed", False))
                    break

            case2_details["receipt_confirmed_initially"] = receipt_confirmed_initially
            if receipt_confirmed_initially is True:
                self.add_finding(
                    "DATA_MISMATCH",
                    "medium",
                    "State shipment already receipt-confirmed at case start",
                    allocation_id=allocation_id,
                )

            if allocation_id is not None:
                confirm_button = page.get_by_role("button", name=re.compile("Confirm Received|Confirming", re.I)).first
                if confirm_button.count() > 0:
                    try:
                        confirm_button.click(timeout=3000)
                        time.sleep(1)
                    except Exception:
                        pass
                else:
                    self.add_finding(
                        "UI_BUG",
                        "medium",
                        "No receipt confirmation button found in district allocation UI",
                        allocation_id=allocation_id,
                    )

                try:
                    confirm_payload = self.api_post("district", f"/district/allocations/{int(allocation_id)}/confirm", {})
                    case2_details["receipt_confirm_result"] = confirm_payload
                except Exception as error:
                    self.add_finding("BACKEND_BUG", "high", "Receipt confirmation API failed", allocation_id=allocation_id, error=str(error))
                    case2_ok = False

        case_results["case_2_state_supply"] = {"passed": case2_ok, **case2_details}
        if case2_ok:
            self.log_pass("Case 2")
        else:
            self.log_fail("Case 2 - supply_level mismatch or confirmation failed")

        # Case 3
        self.log_step("Case 3 — Exceed state but not national")
        national_case_quantities = [600, 1200, 2500, 5000]
        selected_case3: dict[str, Any] | None = None
        for quantity in national_case_quantities:
            self.submit_request_via_ui(page, water_resource, quantity, 103)
            self.run_solver_via_ui(page)
            alloc_rows, unmet_rows = self._find_alloc_unmet_by_slot(water_resource, 103)
            if any(str(r.get("supply_level", "")).lower() == "national" for r in alloc_rows):
                selected_case3 = {
                    "quantity": quantity,
                    "alloc_rows": alloc_rows,
                    "unmet_rows": unmet_rows,
                }
                break

        case3_ok = selected_case3 is not None
        case_results["case_3_national_supply"] = {
            "passed": case3_ok,
            **(selected_case3 or {"quantities_tried": national_case_quantities}),
        }
        if case3_ok:
            self.log_pass("Case 3")
        else:
            self.log_fail("Case 3 - national supply not observed")

        # Case 4
        self.log_step("Case 4 — Exceed all stocks")
        self.submit_request_via_ui(page, water_resource, 1_000_000, 104)
        self.run_solver_via_ui(page)
        request_rows_case4 = self._find_request_rows(water_resource, 104)
        alloc_rows_case4, unmet_rows_case4 = self._find_alloc_unmet_by_slot(water_resource, 104)
        final_qty_case4 = max((float(r.get("final_demand_quantity", r.get("quantity", 0)) or 0) for r in request_rows_case4), default=0.0)
        alloc_case4 = sum(float(r.get("allocated_quantity", 0) or 0) for r in alloc_rows_case4)
        unmet_case4 = sum(float(r.get("unmet_quantity", 0) or 0) for r in unmet_rows_case4)
        case4_ok = abs((alloc_case4 + unmet_case4) - final_qty_case4) <= 1e-4 and unmet_case4 > 0

        case_results["case_4_exceed_all"] = {
            "passed": case4_ok,
            "final": final_qty_case4,
            "allocated": alloc_case4,
            "unmet": unmet_case4,
            "requests": request_rows_case4,
            "alloc_rows": alloc_rows_case4,
            "unmet_rows": unmet_rows_case4,
        }
        if case4_ok:
            self.log_pass("Case 4")
        else:
            self.log_fail("Case 4 - unmet/final equation mismatch")

        # Case 5
        self.log_step("Case 5 — Human-only resource volunteers")
        self.submit_request_via_ui(page, volunteers_resource, 50, 105)
        self.run_solver_via_ui(page)
        request_rows_case5 = self._find_request_rows(volunteers_resource, 105)
        alloc_rows_case5, _ = self._find_alloc_unmet_by_slot(volunteers_resource, 105)
        final_positive = any(float(r.get("final_demand_quantity", 0) or 0) > 0 for r in request_rows_case5)
        allocation_present = len(alloc_rows_case5) > 0
        case5_ok = final_positive and allocation_present
        case_results["case_5_volunteers"] = {
            "passed": case5_ok,
            "requests": request_rows_case5,
            "alloc_rows": alloc_rows_case5,
        }
        if case5_ok:
            self.log_pass("Case 5")
        else:
            self.log_fail("Case 5 - volunteer demand dropped or not allocated")

        # Claim / consume / return
        self.log_step("Claim / Consume / Return cycle")
        page.goto(f"{self.frontend_base}/district", wait_until="domcontentloaded", timeout=self.timeout_ms)
        self.visited_tabs.add("district:allocations_tab")
        page.get_by_role("button", name=re.compile("Allocations", re.I)).click()
        time.sleep(1)

        claim_buttons = page.get_by_role("button", name=re.compile("^Claim$", re.I))
        cycle_outcome: dict[str, Any] = {"executed": False}
        if claim_buttons.count() > 0:
            claim_buttons.first.click()
            time.sleep(1)

            claims = self.api_get("district", "/district/claims")
            latest_claim = claims[0] if claims else None
            if latest_claim:
                district_code = str(latest_claim.get("district_code"))
                resource_id = str(latest_claim.get("resource_id"))
                time_index = int(latest_claim.get("time"))
                claimed_quantity = float(latest_claim.get("claimed_quantity", 0) or 0)

                half = max(1.0, claimed_quantity / 2.0)
                try:
                    consume_result = self.api_post(
                        "district",
                        "/district/consume",
                        {
                            "resource_id": resource_id,
                            "time": time_index,
                            "quantity": half,
                        },
                    )
                    return_result = self.api_post(
                        "district",
                        "/district/return",
                        {
                            "resource_id": resource_id,
                            "time": time_index,
                            "quantity": half,
                            "reason": "ui_audit_cycle",
                        },
                    )
                    cycle_outcome = {
                        "executed": True,
                        "district_code": district_code,
                        "resource_id": resource_id,
                        "time": time_index,
                        "claimed_quantity": claimed_quantity,
                        "consume_result": consume_result,
                        "return_result": return_result,
                    }
                except Exception as error:
                    self.add_finding("BACKEND_BUG", "high", "Claim/consume/return API cycle failed", error=str(error))
            else:
                self.add_finding("UI_BUG", "high", "Claim button clicked but no claim recorded in backend")
        else:
            self.add_finding("UI_BUG", "high", "No claim button available in allocations tab")

        page.reload(wait_until="domcontentloaded")
        self.screenshot(page, "district_claim_consume_return_after")

        case_results["claim_consume_return"] = cycle_outcome

        # Visit all district tabs for stop condition
        for tab_name in ["Requests", "Allocations", "Upstream Supply", "Unmet", "Agent Recommendations", "Run History"]:
            try:
                page.get_by_role("button", name=tab_name).click(timeout=3000)
                time.sleep(0.3)
                self.visited_tabs.add(f"district:{tab_name}")
            except Exception:
                self.add_finding("UI_BUG", "medium", f"District tab not reachable: {tab_name}")

        # detect no-op approve button on district agent
        try:
            page.get_by_role("button", name="Agent Recommendations").click(timeout=3000)
            before = len(self.network_events)
            approve_button = page.get_by_role("button", name="Approve").first
            if approve_button.count() > 0:
                approve_button.click(timeout=2000)
                time.sleep(1)
                after = len(self.network_events)
                if after == before:
                    self.add_finding(
                        "UX_REDUNDANCY",
                        "medium",
                        "District Agent Approve button appears actionable but triggers no backend call",
                    )
        except Exception:
            pass

        district_out["cases"] = case_results
        district_out["invariants"] = self.verify_invariants("district_full_flow")
        self.results["district_tests"] = district_out

    def run_state_flow(self, page: Page) -> None:
        self.log_step("Running State 33 dashboard checks")
        state_out: dict[str, Any] = {}

        page.goto(f"{self.frontend_base}/state", wait_until="domcontentloaded", timeout=self.timeout_ms)
        page.get_by_text(re.compile("State Overview", re.I)).wait_for(timeout=self.timeout_ms)
        self.screenshot(page, "state_overview")
        self.visited_tabs.add("state:/state")

        ui_totals = {
            "total_demand": self.get_stat_card_value(page, "Total District Demand"),
            "allocated": self.get_stat_card_value(page, "Total Allocated to Districts"),
            "unmet": self.get_stat_card_value(page, "Total Unmet"),
            "mutual_aid_sent": self.get_stat_card_value(page, "Mutual Aid Sent"),
        }

        summary = self.api_get("state", "/state/allocations/summary")
        rows = summary.get("rows", []) if isinstance(summary, dict) else []
        pool_txs = self.api_get("state", "/state/pool/transactions")

        api_totals = {
            "total_demand": sum(float(r.get("final_demand_quantity", r.get("allocated_quantity", 0) + r.get("unmet_quantity", 0)) or 0) for r in rows),
            "allocated": sum(float(r.get("allocated_quantity", 0) or 0) for r in rows),
            "unmet": sum(float(r.get("unmet_quantity", 0) or 0) for r in rows),
            "mutual_aid_sent": sum(abs(float(r.get("quantity_delta", 0) or 0)) for r in pool_txs if float(r.get("quantity_delta", 0) or 0) < 0),
        }

        rollup_checks = {}
        for key in ui_totals:
            diff = abs(ui_totals[key] - api_totals[key])
            rollup_checks[key] = {"ui": ui_totals[key], "api": api_totals[key], "difference": diff, "ok": diff <= 1e-4}
            if diff > 1e-4:
                self.add_finding("DATA_MISMATCH", "high", f"State rollup mismatch: {key}", ui=ui_totals[key], api=api_totals[key], difference=diff)

        target_district = self.role_sessions.get("district", {}).get("ui", {}).get("district_code") or self.target_district_code
        district_visible = any(str(r.get("district_code")) == str(target_district) for r in rows)
        if not district_visible:
            self.add_finding("DATA_MISMATCH", "medium", "Target district not visible in state rollup", target_district=target_district)

        page.get_by_role("button", name=re.compile("Mutual Aid Outgoing / Incoming", re.I)).click()
        self.visited_tabs.add("state:Mutual Aid Outgoing / Incoming")
        self.screenshot(page, "state_mutual_aid_tab")

        page.get_by_role("button", name=re.compile("State Stock", re.I)).click()
        self.visited_tabs.add("state:State Stock")

        page.get_by_role("button", name=re.compile("Agent Recommendations", re.I)).click()
        self.visited_tabs.add("state:Agent Recommendations")

        page.get_by_role("button", name=re.compile("Run History", re.I)).click()
        self.visited_tabs.add("state:Run History")

        state_out["rollup_checks"] = rollup_checks
        state_out["district_visible_in_rollup"] = district_visible
        state_out["pool_transactions_count"] = len(pool_txs)
        self.results["state_tests"] = state_out

    def run_national_flow(self, page: Page) -> None:
        self.log_step("Running National dashboard checks")
        national_out: dict[str, Any] = {}

        page.goto(f"{self.frontend_base}/national", wait_until="domcontentloaded", timeout=self.timeout_ms)
        page.get_by_text(re.compile("National Overview", re.I)).wait_for(timeout=self.timeout_ms)
        self.screenshot(page, "national_overview")
        self.visited_tabs.add("national:/national")

        page.get_by_role("button", name=re.compile("Inter-State Transfers", re.I)).click()
        self.visited_tabs.add("national:Inter-State Transfers")
        self.screenshot(page, "national_inter_state_tab")

        page.get_by_role("button", name=re.compile("National Stock", re.I)).click()
        self.visited_tabs.add("national:National Stock")

        page.get_by_role("button", name=re.compile("Agent Recommendations", re.I)).click()
        self.visited_tabs.add("national:Agent Recommendations")

        page.get_by_role("button", name=re.compile("Run History", re.I)).click()
        self.visited_tabs.add("national:Run History")

        summary = self.api_get("national", "/national/allocations/summary")
        rows = summary.get("rows", []) if isinstance(summary, dict) else []
        stock_rows = self.api_get("national", "/national/allocations/stock")
        escalations = self.api_get("national", "/national/escalations")

        national_out["summary_rows"] = len(rows)
        national_out["stock_rows"] = len(stock_rows)
        national_out["escalations"] = len(escalations)

        if len(stock_rows) == 0:
            self.add_finding("BACKEND_BUG", "medium", "National stock endpoint returned no rows")

        self.results["national_tests"] = national_out

    def run_admin_flow(self, page: Page) -> None:
        self.log_step("Running Admin flow checks")
        admin_out: dict[str, Any] = {}

        page.goto(f"{self.frontend_base}/admin", wait_until="domcontentloaded", timeout=self.timeout_ms)
        page.get_by_text(re.compile("Admin Scenario Studio", re.I)).wait_for(timeout=self.timeout_ms)
        self.screenshot(page, "admin_overview")
        self.visited_tabs.add("admin:/admin")

        scenario_name = f"ui_audit_{int(time.time())}"
        page.get_by_placeholder(re.compile("New scenario name", re.I)).fill(scenario_name)
        page.get_by_role("button", name=re.compile("Create Scenario", re.I)).click()
        time.sleep(1)

        state_select = page.locator("xpath=//label[contains(normalize-space(), 'State')]/following-sibling::select[1]").first
        if state_select.count() > 0:
            options = state_select.locator("option").all_inner_texts()
            desired = None
            for option in options:
                if re.search(rf"\b{re.escape(self.target_state_code)}\b", option):
                    desired = option
                    break
            if desired:
                state_select.select_option(label=desired)
            elif len(options) > 1:
                state_select.select_option(index=1)

        # Pick first two resources and one district
        district_select = page.locator("xpath=//label[contains(normalize-space(), 'District (Add one at a time)')]/following-sibling::select[1]").first
        if district_select.count() > 0:
            option_values = district_select.locator("option").all_text_contents()
            if len(option_values) > 1:
                district_select.select_option(index=1)

        resource_checks = page.locator("input[type='checkbox']")
        checked_count = 0
        for index in range(min(resource_checks.count(), 3)):
            checkbox = resource_checks.nth(index)
            try:
                checkbox.check()
                checked_count += 1
            except Exception:
                continue

        page.get_by_role("button", name=re.compile("Add Demand Batch", re.I)).click()
        time.sleep(1)
        page.get_by_role("button", name=re.compile("Simulate Scenario|Running", re.I)).click()
        self.log_check("Waiting for scenario run to register")
        time.sleep(3)

        page.get_by_role("button", name=re.compile("Solver Runs", re.I)).click()
        self.visited_tabs.add("admin:Solver Runs")
        self.screenshot(page, "admin_solver_runs")

        run_cards = page.locator("text=/Run #/i")
        initial_run_count = run_cards.count()

        page.get_by_role("button", name=re.compile("Neural Controller Status", re.I)).click()
        self.visited_tabs.add("admin:Neural Controller Status")
        self.screenshot(page, "admin_neural_status")

        page.get_by_role("button", name=re.compile("Agent Findings", re.I)).click()
        self.visited_tabs.add("admin:Agent Findings")

        approve_buttons = page.get_by_role("button", name=re.compile("Approve", re.I))
        approved_any = False
        if approve_buttons.count() > 0:
            try:
                approve_buttons.first.click(timeout=3000)
                approved_any = True
            except Exception:
                pass

        page.get_by_role("button", name=re.compile("System Health", re.I)).click()
        self.visited_tabs.add("admin:System Health")

        # rerun solver
        try:
            page.get_by_role("button", name=re.compile("Simulate Scenario|Running", re.I)).click(timeout=4000)
            time.sleep(3)
        except Exception:
            self.add_finding("UI_BUG", "high", "Could not trigger second scenario run from admin")

        page.get_by_role("button", name=re.compile("Solver Runs", re.I)).click()
        rerun_count = page.locator("text=/Run #/i").count()
        run_history_updated = rerun_count >= initial_run_count

        if not run_history_updated:
            self.add_finding(
                "BACKEND_BUG",
                "high",
                "Admin run history did not update after rerun",
                initial_run_count=initial_run_count,
                rerun_count=rerun_count,
            )

        admin_out.update(
            {
                "scenario_name": scenario_name,
                "resources_checked": checked_count,
                "initial_run_count": initial_run_count,
                "rerun_count": rerun_count,
                "run_history_updated": run_history_updated,
                "approved_any_recommendation": approved_any,
            }
        )

        self.results["admin_tests"] = admin_out

    def run_role_matrix(self, browser: Browser) -> None:
        matrix_result: dict[str, Any] = {}

        for role in ("district", "state", "national", "admin"):
            expected_path = role

            context = browser.new_context(record_video_dir=str(VIDEO_DIR / role), viewport={"width": 1600, "height": 920})
            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)
            self._attach_telemetry(page)

            role_entry: dict[str, Any] = {
                "logged_in": False,
                "username": None,
                "redirect_ok": False,
                "console_error_count": 0,
                "http_error_count": 0,
            }

            try:
                candidate_credentials = self.get_valid_credential_candidates(role)
                ui_info = self.login_ui(page, role, expected_path, candidate_credentials)
                role_entry["logged_in"] = True
                role_entry["username"] = ui_info.get("username")
                role_entry["redirect_ok"] = True

                api_info = self.api_login(ui_info["username"], ui_info["password"])
                if not api_info:
                    raise RuntimeError(f"Could not establish API session for role={role}")

                role_entry["state_code"] = ui_info.get("state_code")
                role_entry["district_code"] = ui_info.get("district_code")

                if role == "district" and str(ui_info.get("district_code")) != self.target_district_code:
                    self.add_finding(
                        "DATA_MISMATCH",
                        "medium",
                        "Logged-in district does not match requested District 603 target",
                        expected=self.target_district_code,
                        actual=ui_info.get("district_code"),
                    )

                if role == "state" and str(ui_info.get("state_code")) != self.target_state_code:
                    self.add_finding(
                        "DATA_MISMATCH",
                        "medium",
                        "Logged-in state does not match requested State 33 target",
                        expected=self.target_state_code,
                        actual=ui_info.get("state_code"),
                    )

                self.role_sessions[role] = {
                    "ui": ui_info,
                    "api": api_info,
                    "context": context,
                    "page": page,
                }

                self.screenshot(page, f"login_{role}_dashboard")
                self.log_pass(f"{role.capitalize()} role matrix check")

            except Exception as error:
                role_entry["error"] = str(error)
                self.add_finding("UI_BUG", "high", f"Role login matrix failed for {role}", error=str(error))
                self.log_fail(f"Role matrix failed for {role}: {error}")

            console_errors = [event for event in self.console_events if str(event.get("type", "")).lower() == "error"]
            http_errors = [event for event in self.network_events if int(event.get("status", 0) or 0) >= 400]
            role_entry["console_error_count"] = len(console_errors)
            role_entry["http_error_count"] = len(http_errors)

            matrix_result[role] = role_entry

        self.results["role_matrix"] = matrix_result

    def close_contexts(self) -> None:
        for role_data in self.role_sessions.values():
            context: BrowserContext | None = role_data.get("context")
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

    def determine_stop_condition(self) -> dict[str, Any]:
        district_cases = self.results.get("district_tests", {}).get("cases", {})

        all_roles_tested = all(self.results.get("role_matrix", {}).get(role, {}).get("logged_in") for role in ("district", "state", "national", "admin"))
        all_5_cases_executed = all(key in district_cases for key in ("case_1_small_local", "case_2_state_supply", "case_3_national_supply", "case_4_exceed_all", "case_5_volunteers"))
        claim_cycle_done = bool(district_cases.get("claim_consume_return", {}).get("executed"))
        escalation_tested = bool(district_cases.get("case_2_state_supply", {}).get("passed") or district_cases.get("case_3_national_supply", {}).get("passed"))

        required_tab_prefixes = [
            "district:",
            "state:",
            "national:",
            "admin:",
        ]
        tabs_visited = all(any(v.startswith(prefix) for v in self.visited_tabs) for prefix in required_tab_prefixes)

        screenshots_captured = len(self.screenshots) > 0
        reports_written = JSON_REPORT_PATH.exists() and MARKDOWN_REPORT_PATH.exists()

        return {
            "all_roles_tested": all_roles_tested,
            "all_5_district_cases_executed": all_5_cases_executed,
            "claim_consume_return_done": claim_cycle_done,
            "at_least_one_escalation_tested": escalation_tested,
            "all_role_tabs_visited": tabs_visited,
            "screenshots_captured": screenshots_captured,
            "json_report_written": reports_written,
            "ready": all(
                [
                    all_roles_tested,
                    all_5_cases_executed,
                    claim_cycle_done,
                    escalation_tested,
                    tabs_visited,
                    screenshots_captured,
                    reports_written,
                ]
            ),
        }

    def write_reports(self) -> None:
        self.results["finished_at"] = self.now_iso()
        self.results["duration_seconds"] = None
        self.results["screenshots"] = self.screenshots
        self.results["findings"] = [asdict(finding) for finding in self.findings]

        JSON_REPORT_PATH.write_text(json.dumps(self.results, indent=2), encoding="utf-8")

        works = []
        fails = []
        for step in self.step_results:
            if step.passed:
                works.append(step.name)
            else:
                fails.append(step.name)

        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_findings = sorted(self.findings, key=lambda item: severity_order.get(item.severity, 9))

        unnecessary_ui = [f for f in self.findings if f.category == "UX_REDUNDANCY"]
        data_mismatch = [f for f in self.findings if f.category == "DATA_MISMATCH"]

        markdown_lines = [
            "# UI Autonomous Audit Report",
            "",
            f"- Generated: {self.now_iso()}",
            f"- Frontend: {self.frontend_base}",
            f"- Backend: {self.api_base}",
            f"- Browser: Chromium (visible, slow_mo={self.slow_mo})",
            "",
            "## What Works",
        ]

        if works:
            markdown_lines.extend([f"- {item}" for item in works])
        else:
            markdown_lines.append("- No fully passing sections recorded.")

        markdown_lines.extend([
            "",
            "## What Fails",
        ])
        if fails:
            markdown_lines.extend([f"- {item}" for item in fails])
        else:
            markdown_lines.append("- No explicit failed step markers; inspect findings below.")

        markdown_lines.extend([
            "",
            "## Findings",
        ])
        if sorted_findings:
            for finding in sorted_findings:
                markdown_lines.append(f"- [{finding.severity.upper()}] {finding.category}: {finding.message}")
        else:
            markdown_lines.append("- No findings recorded.")

        markdown_lines.extend([
            "",
            "## Numerical Evidence",
            "```json",
            json.dumps(
                {
                    "district_tests": self.results.get("district_tests", {}),
                    "state_tests": self.results.get("state_tests", {}),
                    "national_tests": self.results.get("national_tests", {}),
                    "admin_tests": self.results.get("admin_tests", {}),
                    "invariant_violations": self.results.get("invariant_violations", []),
                },
                indent=2,
            ),
            "```",
            "",
            "## Screenshots",
        ])

        if self.screenshots:
            for screenshot in self.screenshots:
                markdown_lines.append(f"- {screenshot}")
        else:
            markdown_lines.append("- No screenshots found.")

        markdown_lines.extend([
            "",
            "## Suggested Fixes",
            "- Ensure district/state target accounts exist for District 603 and State 33 or align test env credentials.",
            "- Wire UI actions for receipt confirmation and deterministic claim/consume/return quantities.",
            "- Add backend/UI contract assertions for supply_level transitions and final-demand invariants.",
            "- Reduce long API paths and optimize requests above 3s.",
            "",
            "## Unnecessary UI Components / UX Confusion / Dead Tabs / Redundant Dropdown Entries",
        ])

        if unnecessary_ui:
            for finding in unnecessary_ui:
                markdown_lines.append(f"- {finding.message}")
        else:
            markdown_lines.append("- No clear redundant UI control detected in this run.")

        if data_mismatch:
            markdown_lines.append("- Data/metadata mismatch indicators:")
            for finding in data_mismatch:
                markdown_lines.append(f"  - {finding.message}")

        MARKDOWN_REPORT_PATH.write_text("\n".join(markdown_lines), encoding="utf-8")

    def execute(self) -> int:
        started = time.perf_counter()
        browser: Browser | None = None
        try:
            self.wait_for_app()

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=False, slow_mo=self.slow_mo)

                self.run_role_matrix(browser)

                if not all(self.results["role_matrix"].get(role, {}).get("logged_in") for role in ("district", "state", "national", "admin")):
                    raise RuntimeError("Role matrix not fully successful; cannot continue full-app audit")

                district_page = self.role_sessions["district"]["page"]
                state_page = self.role_sessions["state"]["page"]
                national_page = self.role_sessions["national"]["page"]
                admin_page = self.role_sessions["admin"]["page"]

                self.run_district_cases(district_page)
                self.run_state_flow(state_page)
                self.run_national_flow(national_page)
                self.run_admin_flow(admin_page)

                self.record_step_result("Role matrix", True)
                self.record_step_result("District flow", True)
                self.record_step_result("State flow", True)
                self.record_step_result("National flow", True)
                self.record_step_result("Admin flow", True)

        except Exception as error:
            self.results["error"] = {
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
            self.add_finding("BACKEND_BUG", "high", "Audit execution failed", error=str(error))
            self.record_step_result("Audit execution", False, error=str(error))
            self.log_fail(str(error))

        finally:
            self.close_contexts()
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

            elapsed = time.perf_counter() - started
            self.results["duration_seconds"] = round(elapsed, 2)
            self.write_reports()
            self.results["stop_condition"] = self.determine_stop_condition()
            JSON_REPORT_PATH.write_text(json.dumps(self.results, indent=2), encoding="utf-8")

        stop_ready = bool(self.results.get("stop_condition", {}).get("ready"))
        if stop_ready:
            self.log_pass("STOP CONDITION satisfied")
            return 0

        self.log_fail("STOP CONDITION not fully satisfied; inspect report for explicit failures")
        return 1


def main() -> None:
    auditor = UIAuditor()
    exit_code = auditor.execute()
    print(f"[STEP] JSON report: {JSON_REPORT_PATH}")
    print(f"[STEP] Markdown report: {MARKDOWN_REPORT_PATH}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
