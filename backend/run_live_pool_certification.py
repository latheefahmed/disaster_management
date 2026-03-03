from __future__ import annotations

import argparse
import json
import math
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

BASE = "http://127.0.0.1:8000"
DISTRICT_USER = ("district_603", "district123")
STATE_USER = ("state_33", "state123")
NATIONAL_USER = ("national_admin", "national123")

OUT_JSON = Path("LIVE_POOL_CERT_REPORT.json")
OUT_MD = Path("LIVE_POOL_CERT_REPORT.md")
OUT_PROGRESS = Path("LIVE_POOL_CERT_PROGRESS.md")
OUT_TODO = Path("LIVE_POOL_CERT_TODO.md")
OUT_CHECKPOINT = Path("LIVE_POOL_CERT_CHECKPOINT.json")
BASELINE_JSON = Path("baseline_snapshot.json")

TODO_TEMPLATE = [
	{"id": 1, "title": "Capture baseline snapshot", "status": "not-started"},
	{"id": 2, "title": "Execute live certification runs", "status": "not-started"},
	{"id": 3, "title": "Validate invariants and escalation", "status": "not-started"},
	{"id": 4, "title": "Apply restoration actions", "status": "not-started"},
	{"id": 5, "title": "Generate JSON/MD artifacts", "status": "not-started"},
]

PHASES = ["baseline", "selection", "request", "solver", "verify", "aid", "lifecycle", "restore", "report"]


def now_iso() -> str:
	return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def login(username: str, password: str) -> str:
	r = requests.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=30)
	r.raise_for_status()
	return str(r.json()["access_token"])


def headers(token: str) -> dict[str, str]:
	return {"Authorization": f"Bearer {token}"}


def get_json(path: str, token: str, params: dict[str, Any] | None = None, timeout: int = 120) -> Any:
	r = requests.get(f"{BASE}{path}", headers=headers(token), params=params, timeout=timeout)
	r.raise_for_status()
	return r.json()


def post_json(path: str, token: str, payload: dict[str, Any], timeout: int = 120) -> tuple[int, Any]:
	r = requests.post(f"{BASE}{path}", headers=headers(token), json=payload, timeout=timeout)
	try:
		body = r.json()
	except Exception:
		body = {"raw": r.text}
	return int(r.status_code), body


def render_bar(done: int, total: int, width: int = 24) -> str:
	total_safe = max(1, int(total))
	done_safe = max(0, min(int(done), total_safe))
	filled = int(round((done_safe / total_safe) * width))
	return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def to_md_table(rows: list[dict[str, Any]], cols: list[str]) -> str:
	head = "| " + " | ".join(cols) + " |"
	sep = "| " + " | ".join(["---"] * len(cols)) + " |"
	body = ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
	return "\n".join([head, sep] + body)


def set_todo(meta: dict[str, Any], todo_id: int, status: str) -> None:
	for row in meta.get("todos", []):
		if int(row.get("id") or 0) == int(todo_id):
			row["status"] = status
			return


def save_live(meta: dict[str, Any], message: str, attempt: int, phase: str) -> None:
	completed = int(meta.get("stats", {}).get("completed_runs") or 0)
	target_completed = int(meta.get("config", {}).get("target_completed_runs") or 1)
	total_attempts = int(meta.get("config", {}).get("max_attempts") or 1)
	run_bar = render_bar(completed, target_completed)
	attempt_bar = render_bar(attempt, total_attempts)

	phase_index = (PHASES.index(phase) + 1) if phase in PHASES else 0
	phase_bar = render_bar(phase_index, len(PHASES))

	meta["progress"] = {
		"updated_at": now_iso(),
		"completed_runs": completed,
		"target_completed_runs": target_completed,
		"run_line": f"{completed} completed {run_bar} ({completed}/{target_completed})",
		"attempt": int(attempt),
		"attempt_line": f"attempt {attempt} {attempt_bar} ({attempt}/{total_attempts})",
		"phase": phase,
		"phase_line": f"phase {phase} {phase_bar} ({phase_index}/{len(PHASES)})",
		"message": message,
	}

	OUT_CHECKPOINT.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

	progress_lines = [
		"# LIVE POOL CERT Progress",
		"",
		f"Updated: {meta['progress']['updated_at']}",
		"",
		f"- {meta['progress']['run_line']}",
		f"- {meta['progress']['attempt_line']}",
		f"- {meta['progress']['phase_line']}",
		f"- {message}",
	]
	OUT_PROGRESS.write_text("\n".join(progress_lines) + "\n", encoding="utf-8")

	todo_lines = ["# LIVE POOL CERT TODO", "", f"Updated: {meta['progress']['updated_at']}", ""]
	for row in meta.get("todos", []):
		todo_lines.append(f"- [{row.get('status')}] {row.get('id')}. {row.get('title')}")
	OUT_TODO.write_text("\n".join(todo_lines) + "\n", encoding="utf-8")

	print(meta["progress"]["run_line"])
	print(meta["progress"]["attempt_line"])
	print(meta["progress"]["phase_line"])
	print(message)


def stock_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
	out: dict[str, dict[str, float]] = {}
	for row in rows:
		rid = str(row.get("resource_id"))
		out[rid] = {
			"district": float(row.get("district_stock") or 0.0),
			"state": float(row.get("state_stock") or 0.0),
			"national": float(row.get("national_stock") or 0.0),
			"available": float(row.get("available_stock") or 0.0),
		}
	return out


def normalize_qty(meta: dict[str, Any], qty: float) -> float:
	max_reasonable = float(meta.get("max_reasonable_quantity") or meta.get("max_per_resource") or 1000.0)
	value = max(1.0, min(float(qty), max_reasonable))
	if bool(meta.get("requires_integer_quantity")) or str(meta.get("count_type") or "").lower() == "integer":
		value = float(int(value))
		if value < 1:
			value = 1.0
	return float(value)


def discover_neighbor_state() -> tuple[str, str]:
	password_candidates = ["state123", "pw", "password", "state_password"]
	for code in range(1, 100):
		code_str = str(code)
		if code_str == "33":
			continue
		username = f"state_{code_str}"
		for password in password_candidates:
			try:
				token = login(username, password)
				return code_str, token
			except Exception:
				continue
	fallback_code = "32"
	for password in password_candidates:
		try:
			return fallback_code, login(f"state_{fallback_code}", password)
		except Exception:
			continue
	raise RuntimeError("Unable to authenticate any neighbor state user")


def build_default_meta(target_completed_runs: int, max_attempts: int) -> dict[str, Any]:
	return {
		"started_at": now_iso(),
		"config": {
			"district_code": "603",
			"parent_state": "33",
			"target_completed_runs": int(target_completed_runs),
			"max_attempts": int(max_attempts),
		},
		"baseline_snapshot": {},
		"runs": [],
		"stats": {
			"total_runs": 0,
			"completed_runs": 0,
			"invariant_violations": 0,
			"district_only_cases": 0,
			"state_escalations": 0,
			"national_escalations": 0,
			"neighbor_state_cases": 0,
			"manual_aid_cases": 0,
		},
		"final_verdict": "NOT_CERTIFIED",
		"todos": [dict(x) for x in TODO_TEMPLATE],
		"progress": {},
	}


def load_or_init_meta(target_completed_runs: int, max_attempts: int) -> dict[str, Any]:
	if OUT_CHECKPOINT.exists():
		try:
			payload = json.loads(OUT_CHECKPOINT.read_text(encoding="utf-8"))
			if isinstance(payload, dict) and isinstance(payload.get("runs"), list):
				payload.setdefault("config", {})
				payload["config"]["target_completed_runs"] = int(target_completed_runs)
				payload["config"]["max_attempts"] = int(max_attempts)
				payload["todos"] = [dict(x) for x in TODO_TEMPLATE]
				payload.setdefault("stats", {})
				payload["stats"]["total_runs"] = len(payload.get("runs", []))
				payload["stats"]["completed_runs"] = sum(
					1 for r in payload.get("runs", []) if bool(r.get("invariants_pass"))
				)
				payload["stats"]["solver_completed_runs"] = sum(
					1 for r in payload.get("runs", []) if str(r.get("solver_status") or "").lower() == "completed"
				)
				return payload
		except Exception:
			pass
	return build_default_meta(target_completed_runs, max_attempts)


def choose_resource_weighted(
	district_rows: list[dict[str, Any]],
	metadata_map: dict[str, dict[str, Any]],
	rng: random.Random,
) -> dict[str, Any] | None:
	candidates = [row for row in district_rows if str(row.get("resource_id")) in metadata_map]
	if not candidates:
		return None

	sorted_rows = sorted(candidates, key=lambda r: float(r.get("district_stock") or 0.0))
	n = len(sorted_rows)
	split1 = max(1, n // 3)
	split2 = max(split1 + 1, (2 * n) // 3)

	low = sorted_rows[:split1]
	med = sorted_rows[split1:split2] or sorted_rows[:split1]
	high = sorted_rows[split2:] or sorted_rows[-split1:]
	all_rows = sorted_rows

	roll = rng.random()
	if roll < 0.40:
		pool = low
	elif roll < 0.70:
		pool = med
	elif roll < 0.90:
		pool = high
	else:
		pool = all_rows
	return dict(rng.choice(pool))


def classify_escalation_path(allocation_sources: list[str], unmet_total: float) -> str:
	scopes = [s for s in allocation_sources if s]
	scope_set = set(scopes)
	if not scope_set:
		return "unmet_only" if unmet_total > 1e-9 else "none"

	if scope_set == {"district"}:
		return "district_only"
	if scope_set == {"district", "state"}:
		return "district -> state"
	if scope_set == {"district", "state", "national"}:
		return "district -> state -> national"
	if scope_set == {"district", "neighbor_state"}:
		return "district -> neighbor_state"
	if scope_set == {"district", "neighbor_state", "state"}:
		return "district -> neighbor_state -> state"
	if scope_set == {"district", "neighbor_state", "state", "national"}:
		return "district -> neighbor_state -> state -> national"
	if scope_set == {"neighbor_state"}:
		return "neighbor_state_only"
	if scope_set == {"national"}:
		return "national_only"
	if scope_set == {"state"}:
		return "state_only"
	ordered = [x for x in ["district", "neighbor_state", "state", "national"] if x in scope_set]
	return " -> ".join(ordered)


def poll_solver(
	district_token: str,
	meta: dict[str, Any],
	attempt: int,
	trigger_run_id: int,
	max_wait_s: int = 300,
) -> dict[str, Any]:
	if int(trigger_run_id or 0) <= 0:
		return {"status": "harness_error_missing_run_id", "solver_run_id": None}

	started = time.time()
	last: dict[str, Any] = {"solver_run_id": int(trigger_run_id), "status": "running", "mode": "live"}
	while time.time() - started < max_wait_s:
		try:
			run_row = find_run_row(district_token, int(trigger_run_id))
			if isinstance(run_row, dict):
				last = {
					"solver_run_id": int(run_row.get("run_id") or trigger_run_id),
					"status": str(run_row.get("status") or ""),
					"mode": str(run_row.get("mode") or "live"),
					"total_allocated": float(run_row.get("total_allocated") or 0.0),
					"total_unmet": float(run_row.get("total_unmet") or 0.0),
					"total_demand": float(run_row.get("total_demand") or 0.0),
					"started_at": run_row.get("started_at"),
				}
			status = str(last.get("status") or "").lower()
			save_live(
				meta,
				f"Attempt {attempt}: waiting run {trigger_run_id} ({status}, {int(time.time() - started)}s)",
				attempt=attempt,
				phase="solver",
			)
			if status in {"completed", "failed", "failed_reconciliation"}:
				return last
		except Exception as err:
			save_live(
				meta,
				f"Attempt {attempt}: solver poll error: {err}",
				attempt=attempt,
				phase="solver",
			)
		time.sleep(2)

	return {"status": "harness_error_timeout", "solver_run_id": trigger_run_id}


def get_request_row(district_token: str, request_id: int) -> dict[str, Any] | None:
	rows = get_json("/district/requests", district_token, timeout=120)
	if not isinstance(rows, list):
		return None
	for row in rows:
		if int(row.get("id") or 0) == int(request_id):
			return row
	return None


def get_allocations_for_request(district_token: str, request_id: int) -> list[dict[str, Any]]:
	rows = get_json("/district/allocations", district_token, timeout=120)
	if not isinstance(rows, list):
		return []
	return [row for row in rows if int(row.get("request_id") or 0) == int(request_id)]


def get_unmet_rows(district_token: str) -> list[dict[str, Any]]:
	rows = get_json("/district/unmet", district_token, timeout=120)
	if not isinstance(rows, list):
		return []
	return rows


def get_run_history_rows(district_token: str) -> list[dict[str, Any]]:
	rows = get_json("/district/run-history", district_token, timeout=120)
	if not isinstance(rows, list):
		return []
	return rows


def find_run_row(district_token: str, solver_run_id: int) -> dict[str, Any] | None:
	if int(solver_run_id or 0) <= 0:
		return None
	for row in get_run_history_rows(district_token):
		if int(row.get("run_id") or 0) == int(solver_run_id):
			return row
	return None


def latest_live_run_row(district_token: str) -> dict[str, Any] | None:
	for row in get_run_history_rows(district_token):
		if str(row.get("mode") or "").lower() == "live":
			return row
	return None


def parse_iso_utc(value: str | None) -> datetime | None:
	text = str(value or "").strip()
	if not text:
		return None
	try:
		if text.endswith("Z"):
			text = text[:-1] + "+00:00"
		dt = datetime.fromisoformat(text)
		if dt.tzinfo is None:
			return dt.replace(tzinfo=UTC)
		return dt.astimezone(UTC)
	except Exception:
		return None


def is_terminal_request_status(status: str) -> bool:
	return status in {
		"allocated",
		"partial",
		"unmet",
		"failed",
		"escalated_state",
		"escalated_national",
	}


def wait_for_request_terminal(
	district_token: str,
	request_id: int,
	meta: dict[str, Any],
	attempt: int,
	max_wait_s: int = 90,
) -> dict[str, Any] | None:
	started = time.time()
	last: dict[str, Any] | None = None
	while time.time() - started < max_wait_s:
		row = get_request_row(district_token, request_id)
		if isinstance(row, dict):
			last = row
			status = str(row.get("status") or "").lower()
			included = bool(row.get("included_in_run"))
			queued = bool(row.get("queued"))
			save_live(
				meta,
				f"Attempt {attempt}: waiting request {request_id} ({status}, included={included}, queued={queued}, {int(time.time() - started)}s)",
				attempt=attempt,
				phase="verify",
			)
			if is_terminal_request_status(status) and included:
				return row
		else:
			save_live(
				meta,
				f"Attempt {attempt}: request {request_id} not visible yet ({int(time.time() - started)}s)",
				attempt=attempt,
				phase="verify",
			)
		time.sleep(2)
	return last


def wait_for_idle_live_solver(
	district_token: str,
	meta: dict[str, Any],
	attempt: int,
	max_wait_s: int = 300,
) -> dict[str, Any] | None:
	start = time.time()
	last_live: dict[str, Any] | None = None
	while time.time() - start < max_wait_s:
		live_row = latest_live_run_row(district_token)
		last_live = live_row
		status = str((live_row or {}).get("status") or "idle").lower()
		if status != "running":
			return live_row
		save_live(
			meta,
			f"Attempt {attempt}: waiting for active live run to finish ({int(time.time() - start)}s)",
			attempt=attempt,
			phase="solver",
		)
		time.sleep(2)
	return last_live


def get_pool_qty_state(state_token: str, resource_id: str, time_idx: int) -> float:
	rows = get_json("/state/pool", state_token, timeout=120)
	if not isinstance(rows, list):
		return 0.0
	for row in rows:
		if str(row.get("resource_id")) == str(resource_id) and int(row.get("time") or 0) == int(time_idx):
			return float(row.get("quantity") or 0.0)
	return 0.0


def get_pool_qty_national(national_token: str, resource_id: str, time_idx: int) -> float:
	payload = get_json("/national/pool", national_token, timeout=120)
	rows = payload.get("rows") if isinstance(payload, dict) else []
	if not isinstance(rows, list):
		return 0.0
	for row in rows:
		if str(row.get("resource_id")) == str(resource_id) and int(row.get("time") or 0) == int(time_idx):
			return float(row.get("quantity") or 0.0)
	return 0.0


def apply_restoration(
	district_token: str,
	state_token: str,
	national_token: str,
	resource_id: str,
	baseline: dict[str, float],
	current: dict[str, float],
) -> list[dict[str, Any]]:
	actions: list[dict[str, Any]] = []

	district_deficit = float(baseline.get("district", 0.0)) - float(current.get("district", 0.0))
	if district_deficit > 1e-9:
		s, b = post_json(
			"/district/stock/refill",
			district_token,
			{"resource_id": resource_id, "quantity": district_deficit, "note": "phase11_restore_district"},
			timeout=120,
		)
		actions.append({"scope": "district", "quantity": district_deficit, "status": s, "body": b})

	state_deficit = float(baseline.get("state", 0.0)) - float(current.get("state", 0.0))
	if state_deficit > 1e-9:
		s, b = post_json(
			"/state/stock/refill",
			state_token,
			{"resource_id": resource_id, "quantity": state_deficit, "note": "phase11_restore_state"},
			timeout=120,
		)
		actions.append({"scope": "state", "quantity": state_deficit, "status": s, "body": b})

	national_deficit = float(baseline.get("national", 0.0)) - float(current.get("national", 0.0))
	if national_deficit > 1e-9:
		s, b = post_json(
			"/national/stock/refill",
			national_token,
			{"resource_id": resource_id, "quantity": national_deficit, "note": "phase11_restore_national"},
			timeout=120,
		)
		actions.append({"scope": "national", "quantity": national_deficit, "status": s, "body": b})

	return actions


def summarize(meta: dict[str, Any]) -> None:
	runs = meta.get("runs", [])
	completed = sum(1 for r in runs if bool(r.get("invariants_pass")))
	solver_completed = sum(1 for r in runs if str(r.get("solver_status") or "").lower() == "completed")
	total_runs = len(runs)
	inv_viol = sum(1 for r in runs if not bool(r.get("invariants_pass")))

	district_only = sum(1 for r in runs if str(r.get("escalation_path") or "") == "district_only")
	state_esc = sum(1 for r in runs if "state" in str(r.get("escalation_path") or ""))
	national_esc = sum(1 for r in runs if "national" in str(r.get("escalation_path") or ""))
	neighbor_cases = sum(1 for r in runs if "neighbor_state" in str(r.get("escalation_path") or ""))
	aid_cases = sum(1 for r in runs if bool((r.get("manual_aid") or {}).get("used")))

	solver_rate = (solver_completed / total_runs) if total_runs else 0.0

	meta["summary"] = {
		"total_runs": total_runs,
		"completed_runs": completed,
		"solver_completed_runs": solver_completed,
		"solver_complete_rate": round(solver_rate, 6),
		"invariant_violations": inv_viol,
		"district_only_cases": district_only,
		"state_escalations": state_esc,
		"national_escalations": national_esc,
		"neighbor_state_cases": neighbor_cases,
		"manual_aid_cases": aid_cases,
	}

	certified = (
		total_runs >= int(meta.get("config", {}).get("target_completed_runs") or 60)
		and solver_rate >= 0.95
		and inv_viol == 0
		and state_esc >= 10
		and national_esc >= 5
		and neighbor_cases >= 3
	)
	meta["final_verdict"] = "CERTIFIED" if certified else "NOT_CERTIFIED"

	meta["stats"] = {
		"total_runs": total_runs,
		"completed_runs": completed,
		"solver_completed_runs": solver_completed,
		"invariant_violations": inv_viol,
		"district_only_cases": district_only,
		"state_escalations": state_esc,
		"national_escalations": national_esc,
		"neighbor_state_cases": neighbor_cases,
		"manual_aid_cases": aid_cases,
	}


def write_reports(meta: dict[str, Any]) -> None:
	OUT_JSON.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

	rows = []
	for r in meta.get("runs", []):
		rows.append(
			{
				"run_id": r.get("run_id"),
				"resource_id": r.get("resource_id"),
				"time": r.get("time"),
				"priority": r.get("priority"),
				"urgency": r.get("urgency"),
				"request_qty": r.get("request_qty"),
				"solver_status": r.get("solver_status"),
				"allocated_total": r.get("allocated_total"),
				"unmet_total": r.get("unmet_total"),
				"escalation_path": r.get("escalation_path"),
				"manual_aid": bool((r.get("manual_aid") or {}).get("used")),
				"invariants_pass": r.get("invariants_pass"),
				"failure_reason": r.get("failure_reason"),
			}
		)

	s = meta.get("summary") or {}
	lines = [
		"# LIVE POOL CERT REPORT",
		"",
		f"- Generated: {now_iso()}",
		f"- Started: {meta.get('started_at')}",
		f"- Target Runs: {meta.get('config', {}).get('target_completed_runs')}",
		f"- Executed Runs: {s.get('total_runs')}",
		f"- Solver Complete Rate: {round(float(s.get('solver_complete_rate') or 0.0) * 100, 2)}%",
		f"- Invariant Violations: {s.get('invariant_violations')}",
		f"- State Escalations Seen: {s.get('state_escalations')}",
		f"- National Escalations Seen: {s.get('national_escalations')}",
		f"- Neighbor State Cases: {s.get('neighbor_state_cases')}",
		f"- Manual Aid Cases: {s.get('manual_aid_cases')}",
		f"- Final Verdict: {meta.get('final_verdict')}",
		"",
		"## Run Results",
		"",
		to_md_table(
			rows,
			[
				"run_id",
				"resource_id",
				"time",
				"priority",
				"urgency",
				"request_qty",
				"solver_status",
				"allocated_total",
				"unmet_total",
				"escalation_path",
				"manual_aid",
				"invariants_pass",
				"failure_reason",
			],
		),
	]
	OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--target-completed-runs", type=int, default=60)
	parser.add_argument("--max-attempts", type=int, default=120)
	parser.add_argument("--seed", type=int, default=60311)
	args = parser.parse_args()

	target_completed = max(1, int(args.target_completed_runs))
	max_attempts = max(target_completed, int(args.max_attempts))

	meta = load_or_init_meta(target_completed, max_attempts)
	rng = random.Random(int(args.seed))

	district_token = login(*DISTRICT_USER)
	state_token = login(*STATE_USER)
	national_token = login(*NATIONAL_USER)
	neighbor_state_code, neighbor_token = discover_neighbor_state()
	meta["config"]["neighbor_state"] = neighbor_state_code

	set_todo(meta, 1, "in-progress")
	save_live(meta, "Initializing baseline snapshot", attempt=0, phase="baseline")

	resources = get_json("/metadata/resources", district_token)
	district_stock = get_json("/district/stock", district_token)
	state_stock = get_json("/state/stock", state_token)
	national_stock = get_json("/national/stock", national_token)

	baseline_snapshot = {
		"district_stock": district_stock,
		"state_stock": state_stock,
		"national_stock": national_stock,
		"resource_metadata": resources,
		"captured_at": now_iso(),
	}
	BASELINE_JSON.write_text(json.dumps(baseline_snapshot, indent=2, default=str), encoding="utf-8")
	meta["baseline_snapshot"] = baseline_snapshot

	metadata_map = {str(r.get("resource_id")): r for r in resources if isinstance(r, dict)}
	baseline_stock_map = stock_map(district_stock)

	set_todo(meta, 1, "completed")
	set_todo(meta, 2, "in-progress")
	save_live(meta, "Baseline captured; starting certification loop", attempt=0, phase="selection")

	existing_runs = len(meta.get("runs", []))
	completed_runs = int(meta.get("stats", {}).get("completed_runs") or 0)
	attempt = existing_runs

	while attempt < max_attempts and completed_runs < target_completed:
		attempt += 1
		run_id = attempt

		idle_row = wait_for_idle_live_solver(
			district_token=district_token,
			meta=meta,
			attempt=attempt,
			max_wait_s=300,
		)
		if str((idle_row or {}).get("status") or "idle").lower() == "running":
			run = {
				"run_id": run_id,
				"solver_status": "harness_error",
				"failure_reason": "active_live_run_never_idle",
				"invariants_pass": False,
			}
			meta["runs"].append(run)
			summarize(meta)
			save_live(meta, f"Attempt {attempt}: aborted (live run remained running)", attempt=attempt, phase="verify")
			continue

		save_live(meta, f"Attempt {attempt}: selecting resource", attempt=attempt, phase="selection")

		district_rows = get_json("/district/stock", district_token)
		pick = choose_resource_weighted(district_rows, metadata_map, rng)
		if not pick:
			run = {
				"run_id": run_id,
				"solver_status": "harness_error",
				"failure_reason": "no_resource_candidates",
				"invariants_pass": False,
			}
			meta["runs"].append(run)
			continue

		rid = str(pick.get("resource_id"))
		m = metadata_map.get(rid, {})
		pre_map = stock_map(district_rows)
		pre = pre_map.get(rid, {"district": 0.0, "state": 0.0, "national": 0.0, "available": 0.0})

		qty_raw = (float(pre["district"]) * 0.8) + (float(pre["state"]) * 0.3) + (float(pre["national"]) * 0.1)
		qty = normalize_qty(m, max(1.0, round(qty_raw)))

		time_idx = int(rng.choice([0, 1, 2, 3, 4]))
		priority = int(rng.choice([1, 2, 3, 4, 5]))
		urgency = int(rng.choice([1, 2, 3, 4, 5]))

		save_live(meta, f"Attempt {attempt}: creating request for {rid}", attempt=attempt, phase="request")
		req_status, req_body = post_json(
			"/district/request",
			district_token,
			{
				"resource_id": rid,
				"time": time_idx,
				"quantity": qty,
				"priority": priority,
				"urgency": urgency,
				"confidence": 1.0,
				"source": "human",
			},
			timeout=90,
		)
		request_id = int((req_body or {}).get("request_id") or 0)
		request_solver_run_id = int((req_body or {}).get("solver_run_id") or 0)
		req_row_created = get_request_row(district_token, request_id) if request_id > 0 else None
		if req_status < 200 or req_status >= 300 or request_id <= 0:
			run = {
				"run_id": run_id,
				"resource_id": rid,
				"time": time_idx,
				"priority": priority,
				"urgency": urgency,
				"request_qty": qty,
				"solver_status": "harness_error",
				"allocated_total": 0.0,
				"unmet_total": 0.0,
				"escalation_path": "none",
				"allocation_sources": [],
				"request_id": request_id,
				"request_status": "",
				"request_create": {"status": req_status, "body": req_body},
				"invariants_pass": False,
				"failure_reason": "request_create_failed",
			}
			meta["runs"].append(run)
			summarize(meta)
			save_live(meta, f"Attempt {attempt}: request create failed", attempt=attempt, phase="verify")
			continue

		save_live(meta, f"Attempt {attempt}: binding solver run", attempt=attempt, phase="solver")
		trig_status, trig_body = 200, {"solver_run_id": request_solver_run_id, "source": "request_create"}
		trigger_run_id = int(request_solver_run_id or 0)

		if trigger_run_id <= 0:
			save_live(meta, f"Attempt {attempt}: triggering solver fallback", attempt=attempt, phase="solver")
			try:
				trig_status, trig_body = post_json("/district/run", district_token, {}, timeout=300)
			except Exception as err:
				trig_status, trig_body = 599, {"detail": f"run trigger timeout/error: {err}"}
			trigger_run_id = int((trig_body or {}).get("solver_run_id") or 0)
		if trigger_run_id <= 0:
			latest_live = latest_live_run_row(district_token)
			if str((latest_live or {}).get("status") or "").lower() == "running":
				trigger_run_id = int((latest_live or {}).get("run_id") or 0)

		if trigger_run_id > 0 and isinstance(req_row_created, dict):
			run_row = find_run_row(district_token, trigger_run_id)
			run_started = parse_iso_utc(str((run_row or {}).get("started_at") or ""))
			req_created = parse_iso_utc(str((req_row_created or {}).get("created_at") or ""))
			if run_started is not None and req_created is not None and run_started <= req_created:
				wait_for_idle_live_solver(
					district_token=district_token,
					meta=meta,
					attempt=attempt,
					max_wait_s=300,
				)
				try:
					retry_status, retry_body = post_json("/district/run", district_token, {}, timeout=300)
				except Exception as err:
					retry_status, retry_body = 599, {"detail": f"run retrigger timeout/error: {err}"}
				retry_run_id = int((retry_body or {}).get("solver_run_id") or 0)
				if retry_run_id > 0:
					trigger_run_id = retry_run_id
					trig_status, trig_body = retry_status, retry_body
		if trigger_run_id <= 0:
			run = {
				"run_id": run_id,
				"resource_id": rid,
				"time": time_idx,
				"priority": priority,
				"urgency": urgency,
				"request_qty": qty,
				"solver_status": "harness_error",
				"allocated_total": 0.0,
				"unmet_total": 0.0,
				"escalation_path": "none",
				"allocation_sources": [],
				"request_id": request_id,
				"request_status": "",
				"run_trigger": {"status": trig_status, "body": trig_body},
				"invariants_pass": False,
				"failure_reason": "solver_run_id_missing",
			}
			meta["runs"].append(run)
			summarize(meta)
			save_live(meta, f"Attempt {attempt}: missing solver_run_id", attempt=attempt, phase="verify")
			continue
		solver = poll_solver(
			district_token=district_token,
			meta=meta,
			attempt=attempt,
			trigger_run_id=trigger_run_id,
			max_wait_s=300,
		)
		solver_status = str((solver or {}).get("status") or "").lower()

		save_live(meta, f"Attempt {attempt}: collecting post-run snapshots", attempt=attempt, phase="verify")
		req_row = get_request_row(district_token, request_id) if request_id > 0 else None
		if request_id > 0 and solver_status == "completed":
			req_row = wait_for_request_terminal(
				district_token=district_token,
				request_id=request_id,
				meta=meta,
				attempt=attempt,
				max_wait_s=90,
			) or req_row
		all_alloc_rows = get_json("/district/allocations", district_token, timeout=120)
		all_unmet_rows = get_unmet_rows(district_token)
		if not isinstance(all_alloc_rows, list):
			all_alloc_rows = []

		alloc_rows = [
			r for r in all_alloc_rows
			if int(r.get("solver_run_id") or 0) == int(trigger_run_id)
			and str(r.get("resource_id") or "") == rid
			and int(r.get("time") or 0) == int(time_idx)
		]
		alloc_rows_by_request = [r for r in alloc_rows if int(r.get("request_id") or 0) == int(request_id)]
		got_rows = alloc_rows_by_request if alloc_rows_by_request else alloc_rows

		unmet_rows = [
			r for r in all_unmet_rows
			if int(r.get("solver_run_id") or 0) == int(trigger_run_id)
			and str(r.get("resource_id") or "") == rid
			and int(r.get("time") or 0) == int(time_idx)
		]

		alloc_total = float(sum(float(r.get("allocated_quantity") or 0.0) for r in got_rows))
		unmet_total = float(sum(float(r.get("unmet_quantity") or r.get("allocated_quantity") or 0.0) for r in unmet_rows))

		source_scopes = [str(r.get("allocation_source_scope") or r.get("supply_level") or "") for r in got_rows]
		source_codes = [
			str(r.get("allocation_source_code") or r.get("origin_state_code") or r.get("state_code") or "") for r in got_rows
		]

		escalation_path = classify_escalation_path(source_scopes, unmet_total)

		save_live(meta, f"Attempt {attempt}: manual aid check", attempt=attempt, phase="aid")
		manual_aid: dict[str, Any] = {"used": False}
		if attempt % 5 == 0 and unmet_total > 1e-9:
			remaining = float(unmet_total)

			state_qty = get_pool_qty_state(state_token, rid, time_idx)
			give_state = max(0.0, min(remaining, state_qty))
			if give_state > 1e-9:
				s_status, s_body = post_json(
					"/state/pool/allocate",
					state_token,
					{
						"resource_id": rid,
						"time": time_idx,
						"quantity": give_state,
						"target_district": "603",
						"note": "phase11_manual_aid_state",
					},
					timeout=120,
				)
				manual_aid["state_pool_allocate"] = {"status": s_status, "quantity": give_state, "body": s_body}

			req_row_after_state = get_request_row(district_token, request_id) if request_id > 0 else None
			remaining_after_state = float((req_row_after_state or {}).get("unmet_quantity") or remaining)

			neighbor_accepted_qty = 0.0
			if remaining_after_state > 1e-9:
				neighbor_target = max(1.0, min(remaining_after_state, remaining_after_state * 0.6))
				ma_status, ma_body = post_json(
					"/district/mutual-aid/request",
					district_token,
					{
						"resource_id": rid,
						"quantity_requested": neighbor_target,
						"time": time_idx,
					},
					timeout=120,
				)
				manual_aid["neighbor_request"] = {
					"status": ma_status,
					"quantity_requested": neighbor_target,
					"body": ma_body,
				}

				ma_request_id = int((ma_body or {}).get("request_id") or 0)
				if ma_status == 200 and ma_request_id > 0:
					o_status, o_body = post_json(
						"/state/mutual-aid/offers",
						neighbor_token,
						{
							"request_id": ma_request_id,
							"quantity_offered": neighbor_target,
						},
						timeout=120,
					)
					manual_aid["neighbor_offer"] = {
						"status": o_status,
						"quantity_offered": neighbor_target,
						"body": o_body,
					}

					offer_id = int((o_body or {}).get("offer_id") or 0)
					if o_status == 200 and offer_id > 0:
						accept_neighbor = bool((attempt % 2) == 0 or priority >= 4 or urgency >= 4)
						decision = "accepted" if accept_neighbor else "rejected"
						r_status2, r_body2 = post_json(
							f"/state/mutual-aid/offers/{offer_id}/respond",
							state_token,
							{"decision": decision},
							timeout=120,
						)
						manual_aid["neighbor_offer_response"] = {
							"status": r_status2,
							"decision": decision,
							"body": r_body2,
						}
						if r_status2 == 200 and decision == "accepted":
							neighbor_accepted_qty = float(neighbor_target)

			remaining_after_neighbor = max(0.0, remaining_after_state - neighbor_accepted_qty)

			if remaining_after_neighbor > 1e-9:
				n_status, n_body = post_json(
					"/national/pool/allocate",
					national_token,
					{
						"state_code": "33",
						"resource_id": rid,
						"time": time_idx,
						"quantity": remaining_after_neighbor,
						"target_district": "603",
						"note": "phase11_manual_aid_national",
					},
					timeout=120,
				)
				manual_aid["national_pool_allocate"] = {
					"status": n_status,
					"quantity": remaining_after_neighbor,
					"body": n_body,
				}

			try:
				r_status, r_body = post_json("/district/run", district_token, {}, timeout=300)
			except Exception as err:
				r_status, r_body = 599, {"detail": f"manual-aid rerun trigger timeout/error: {err}"}
			rerun_id = int((r_body or {}).get("solver_run_id") or 0)
			if rerun_id <= 0:
				latest_live = latest_live_run_row(district_token)
				if str((latest_live or {}).get("status") or "").lower() == "running":
					rerun_id = int((latest_live or {}).get("run_id") or 0)
			solver2 = poll_solver(
				district_token=district_token,
				meta=meta,
				attempt=attempt,
				trigger_run_id=rerun_id,
				max_wait_s=300,
			)
			req_row = get_request_row(district_token, request_id) if request_id > 0 else req_row
			all_alloc_rows = get_json("/district/allocations", district_token, timeout=120)
			all_unmet_rows = get_unmet_rows(district_token)
			if not isinstance(all_alloc_rows, list):
				all_alloc_rows = []

			effective_run_id = rerun_id if rerun_id > 0 else trigger_run_id
			alloc_rows = [
				r for r in all_alloc_rows
				if int(r.get("solver_run_id") or 0) == int(effective_run_id)
				and str(r.get("resource_id") or "") == rid
				and int(r.get("time") or 0) == int(time_idx)
			]
			alloc_rows_by_request = [r for r in alloc_rows if int(r.get("request_id") or 0) == int(request_id)]
			got_rows = alloc_rows_by_request if alloc_rows_by_request else alloc_rows
			unmet_rows = [
				r for r in all_unmet_rows
				if int(r.get("solver_run_id") or 0) == int(effective_run_id)
				and str(r.get("resource_id") or "") == rid
				and int(r.get("time") or 0) == int(time_idx)
			]
			alloc_total = float(sum(float(r.get("allocated_quantity") or 0.0) for r in got_rows))
			unmet_total = float(sum(float(r.get("unmet_quantity") or r.get("allocated_quantity") or 0.0) for r in unmet_rows))
			source_scopes = [str(r.get("allocation_source_scope") or r.get("supply_level") or "") for r in got_rows]
			source_codes = [
				str(r.get("allocation_source_code") or r.get("origin_state_code") or r.get("state_code") or "")
				for r in got_rows
			]
			neighbor_resp = manual_aid.get("neighbor_offer_response") if isinstance(manual_aid, dict) else None
			if isinstance(neighbor_resp, dict) and int(neighbor_resp.get("status") or 0) == 200 and str(neighbor_resp.get("decision") or "").lower() == "accepted":
				if "neighbor_state" not in source_scopes:
					source_scopes.append("neighbor_state")
				neighbor_body = manual_aid.get("neighbor_offer", {}).get("body", {}) if isinstance(manual_aid.get("neighbor_offer"), dict) else {}
				neighbor_code = str((neighbor_body or {}).get("offering_state") or meta.get("config", {}).get("neighbor_state") or "")
				if neighbor_code:
					source_codes.append(neighbor_code)

			national_aid = manual_aid.get("national_pool_allocate") if isinstance(manual_aid, dict) else None
			if isinstance(national_aid, dict) and int(national_aid.get("status") or 0) == 200:
				if "national" not in source_scopes:
					source_scopes.append("national")
				source_codes.append("NATIONAL")
			escalation_path = classify_escalation_path(source_scopes, unmet_total)
			manual_aid["used"] = True
			manual_aid["rerun"] = {"status": r_status, "body": r_body, "solver": solver2}

		save_live(meta, f"Attempt {attempt}: claim/consume/return", attempt=attempt, phase="lifecycle")
		ccr: dict[str, Any] = {}
		if got_rows:
			first = got_rows[0]
			action_qty = max(1.0, min(float(first.get("allocated_quantity") or 0.0), 1.0))
			claim_status, claim_body = post_json(
				"/district/claim",
				district_token,
				{
					"resource_id": rid,
					"time": int(first.get("time") or time_idx),
					"quantity": action_qty,
					"claimed_by": "phase11_cert",
					"solver_run_id": int(first.get("solver_run_id") or 0),
				},
				timeout=120,
			)
			ccr["claim"] = {"status": claim_status, "body": claim_body}

			cls = str(m.get("class") or "").lower()
			if claim_status == 200 and cls == "consumable":
				consume_status, consume_body = post_json(
					"/district/consume",
					district_token,
					{
						"resource_id": rid,
						"time": int(first.get("time") or time_idx),
						"quantity": action_qty,
						"solver_run_id": int(first.get("solver_run_id") or 0),
					},
					timeout=120,
				)
				ccr["consume"] = {"status": consume_status, "body": consume_body}
			elif claim_status == 200:
				src_scope = str(first.get("allocation_source_scope") or first.get("supply_level") or "")
				src_code = str(first.get("allocation_source_code") or first.get("origin_state_code") or first.get("state_code") or "")
				return_status, return_body = post_json(
					"/district/return",
					district_token,
					{
						"resource_id": rid,
						"time": int(first.get("time") or time_idx),
						"quantity": action_qty,
						"reason": "manual",
						"solver_run_id": int(first.get("solver_run_id") or 0),
						"allocation_source_scope": src_scope,
						"allocation_source_code": src_code,
					},
					timeout=120,
				)
				ccr["return"] = {
					"status": return_status,
					"body": return_body,
					"source_scope": src_scope,
					"source_code": src_code,
				}

		save_live(meta, f"Attempt {attempt}: restoration", attempt=attempt, phase="restore")
		post_rows = get_json("/district/stock", district_token)
		post_map = stock_map(post_rows)
		post = post_map.get(rid, {"district": 0.0, "state": 0.0, "national": 0.0, "available": 0.0})

		base_for_resource = baseline_stock_map.get(rid, {"district": 0.0, "state": 0.0, "national": 0.0, "available": 0.0})
		restoration_actions = apply_restoration(
			district_token=district_token,
			state_token=state_token,
			national_token=national_token,
			resource_id=rid,
			baseline=base_for_resource,
			current=post,
		)

		request_status = str((req_row or {}).get("status") or "").lower()
		if escalation_path == "none" and request_status == "escalated_state":
			escalation_path = "district -> state"
		elif escalation_path == "none" and request_status == "escalated_national":
			escalation_path = "district -> state -> national"
		included = bool((req_row or {}).get("included_in_run"))
		final_demand = float((req_row or {}).get("final_demand_quantity") or 0.0)
		req_alloc = float(alloc_total)
		req_unmet = float(unmet_total)
		request_terminal = is_terminal_request_status(request_status)

		if final_demand <= 1e-9 and (req_alloc + req_unmet) > 1e-9:
			final_demand = req_alloc + req_unmet
		conservation_required = request_status in {"allocated", "partial", "unmet", "failed"}
		conservation = (not conservation_required) or (not math.isfinite(final_demand)) or final_demand <= 1e-9 or abs(final_demand - (req_alloc + req_unmet)) <= 1e-6
		no_pending = request_status != "pending"
		non_negative_stock = all(post[k] >= -1e-9 for k in ["district", "state", "national", "available"])
		provenance_ok = all(s in {"district", "state", "neighbor_state", "national"} for s in source_scopes)
		run_completed = solver_status == "completed"
		request_in_run = included

		invariants_pass = bool(
			run_completed and request_terminal and request_in_run and conservation and no_pending and non_negative_stock and provenance_ok
		)
		failure_reason = None if invariants_pass else (
			"solver_not_completed" if not run_completed else
			"request_not_terminal" if not request_terminal else
			"request_not_included_in_run" if not request_in_run else
			"conservation_failed" if not conservation else
			"pending_request" if not no_pending else
			"negative_stock" if not non_negative_stock else
			"allocation_provenance_missing"
		)

		run = {
			"run_id": run_id,
			"resource_id": rid,
			"time": time_idx,
			"priority": priority,
			"urgency": urgency,
			"request_qty": qty,
			"solver_status": solver_status,
			"allocated_total": alloc_total,
			"unmet_total": unmet_total,
			"escalation_path": escalation_path,
			"allocation_sources": [
				{
					"scope": source_scopes[i],
					"code": source_codes[i],
					"qty": float(got_rows[i].get("allocated_quantity") or 0.0),
				}
				for i in range(len(got_rows))
			],
			"manual_aid": manual_aid if manual_aid else None,
			"claim_consume_return": ccr,
			"pre_stock": pre,
			"post_stock": post,
			"stock_deltas": {
				"district": round(float(post["district"]) - float(pre["district"]), 6),
				"state": round(float(post["state"]) - float(pre["state"]), 6),
				"national": round(float(post["national"]) - float(pre["national"]), 6),
				"available": round(float(post["available"]) - float(pre["available"]), 6),
			},
			"request_id": request_id,
			"request_status": request_status,
			"trigger_run_id": trigger_run_id,
			"run_trigger": {"status": trig_status, "body": trig_body},
			"solver": solver,
			"restoration_actions": restoration_actions,
			"invariants_pass": invariants_pass,
			"failure_reason": failure_reason,
		}

		meta["runs"].append(run)
		summarize(meta)

		completed_runs = int(meta.get("stats", {}).get("completed_runs") or 0)

		set_todo(meta, 3, "in-progress")
		set_todo(meta, 4, "in-progress")
		save_live(meta, f"Attempt {attempt}: run captured", attempt=attempt, phase="verify")

	set_todo(meta, 2, "completed")
	set_todo(meta, 3, "completed")
	set_todo(meta, 4, "completed")
	set_todo(meta, 5, "in-progress")

	summarize(meta)
	write_reports(meta)

	set_todo(meta, 5, "completed")
	save_live(meta, f"Certification complete: {meta.get('final_verdict')}", attempt=len(meta.get('runs', [])), phase="report")

	print(json.dumps(meta.get("summary", {}), indent=2))
	print(f"final_verdict={meta.get('final_verdict')}")
	print(f"report_json={OUT_JSON}")
	print(f"report_md={OUT_MD}")
	print(f"baseline={BASELINE_JSON}")


if __name__ == "__main__":
	main()
