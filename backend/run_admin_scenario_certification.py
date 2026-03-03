from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _report_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parent
    return root / "ADMIN_SCENARIO_CERT_REPORT.json", root / "ADMIN_SCENARIO_CERT_REPORT.md"


def _safe_json(response) -> dict[str, Any]:
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"payload": payload}
    except Exception:
        return {"raw": getattr(response, "text", "")}


_PRESET_TARGETS: dict[str, dict[str, Any]] = {
    "very_low": {
        "ratio_min": 0.30,
        "ratio_max": 0.95,
        "district_choices": [2, 3],
        "resource_choices": [2, 3],
        "horizon_choices": [1, 2],
        "stress": False,
    },
    "low": {
        "ratio_min": 0.70,
        "ratio_max": 1.20,
        "district_choices": [3, 4],
        "resource_choices": [2, 3],
        "horizon_choices": [1, 2],
        "stress": False,
    },
    "medium": {
        "ratio_min": 0.90,
        "ratio_max": 1.70,
        "district_choices": [4, 5],
        "resource_choices": [3, 4],
        "horizon_choices": [2, 3],
        "stress": False,
    },
    "high": {
        "ratio_min": 1.20,
        "ratio_max": 2.30,
        "district_choices": [5, 6],
        "resource_choices": [3, 4],
        "horizon_choices": [2, 3],
        "stress": False,
    },
    "extreme": {
        "ratio_min": 1.60,
        "ratio_max": 3.20,
        "district_choices": [6, 7],
        "resource_choices": [4, 5],
        "horizon_choices": [2, 3],
        "stress": True,
    },
}


def _pick_state_codes(idx: int, state_codes: list[str], width: int) -> list[str]:
    if not state_codes:
        return []
    window = max(1, min(int(width), len(state_codes)))
    start = int((idx - 1) % len(state_codes))
    selected: list[str] = []
    for offset in range(window):
        selected.append(str(state_codes[(start + offset) % len(state_codes)]))
    return selected


def _build_variant(idx: int, preset: str, state_codes: list[str], attempt: int = 0) -> dict[str, Any]:
    cfg = _PRESET_TARGETS[str(preset)]
    district_choices = list(cfg["district_choices"])
    resource_choices = list(cfg["resource_choices"])
    horizon_choices = list(cfg["horizon_choices"])

    district_count = int(district_choices[(idx + attempt) % len(district_choices)])
    resource_count = int(resource_choices[(idx + 2 * attempt) % len(resource_choices)])
    time_horizon = int(horizon_choices[(idx + attempt) % len(horizon_choices)])

    payload = {
        "preset": str(preset),
        "seed": 20260301 + (idx * 17) + attempt,
        "time_horizon": time_horizon,
        "district_count": district_count,
        "resource_count": resource_count,
        "stress_mode": bool(cfg.get("stress", False) and ((idx + attempt) % 2 == 0)),
        "replace_existing": True,
    }

    picked_states = _pick_state_codes(idx=idx + attempt, state_codes=state_codes, width=(1 + (idx % 2)))
    if picked_states:
        payload["state_codes"] = picked_states

    return payload


def _ratio_in_band(preset: str, ratio_value: float | None) -> bool:
    if ratio_value is None:
        return False
    cfg = _PRESET_TARGETS[str(preset)]
    return float(cfg["ratio_min"]) <= float(ratio_value) <= float(cfg["ratio_max"])


def _extract_failure_detail(run_resp) -> str:
    payload = _safe_json(run_resp)
    detail = payload.get("detail")
    if detail is not None:
        return str(detail)
    raw = payload.get("raw")
    if raw is not None:
        return str(raw)
    return str(payload)


def _classify_run_failure(status_code: int, detail_text: str) -> str:
    text = str(detail_text or "").lower()
    if int(status_code) == 422 and "preflight_failed" in text:
        return "preflight"
    if "timed out" in text or "time out" in text or "timeout" in text:
        return "solver_timeout"
    if "solver execution failed" in text:
        return "solver_process"
    if int(status_code) >= 500:
        return "runtime"
    return "unknown"


def _cycle_template(idx: int, preset: str) -> dict[str, Any]:
    return {
        "cycle": idx,
        "preset": preset,
        "scenario_name": f"AUTO_ADMIN_CERT_{idx}_{datetime.now(timezone.utc).strftime('%H%M%S')}",
        "scenario_id": 0,
        "create_status": None,
        "randomizer_preview_status": None,
        "randomizer_apply_status": None,
        "run_status": None,
        "run_failure_detail": None,
        "run_failure_class": None,
        "run_retry_count": 0,
        "run_id": None,
        "summary_status": None,
        "revert_status": None,
        "verify_status": None,
        "verify_ok": False,
        "verify_net_total": None,
        "verify_debit_total": None,
        "verify_revert_total": None,
        "randomizer_demand_ratio": None,
        "randomizer_row_count": None,
        "randomizer_warning_count": 0,
        "variant_used": None,
        "pass": False,
        "notes": [],
        "started_at": _now(),
        "finished_at": None,
    }


def run_certification(target_runs: int = 12, run_scope: str = "focused") -> dict[str, Any]:
    presets = ["very_low", "low", "medium", "high", "extreme"]
    run_count = max(10, min(30, int(target_runs)))
    normalized_scope = str(run_scope or "focused").strip().lower()
    if normalized_scope not in {"focused", "full"}:
        normalized_scope = "focused"

    client = TestClient(app, raise_server_exceptions=False)

    login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    if login.status_code != 200:
        raise RuntimeError(f"Admin login failed: {login.status_code} {login.text}")

    token = login.json().get("access_token")
    if not token:
        raise RuntimeError("Admin token missing")
    headers = {"Authorization": f"Bearer {token}"}

    states_resp = client.get("/metadata/states", headers=headers)
    state_codes: list[str] = []
    if states_resp.status_code == 200:
        state_codes = [str(x.get("state_code")) for x in (states_resp.json() or []) if x.get("state_code")]

    cycles: list[dict[str, Any]] = []
    scenarios_created: list[int] = []

    for i in range(1, run_count + 1):
        preset = presets[(i - 1) % len(presets)]
        cycle = _cycle_template(i, preset)

        try:
            create_resp = client.post("/admin/scenarios", headers=headers, json={"name": cycle["scenario_name"]})
            cycle["create_status"] = int(create_resp.status_code)
            if create_resp.status_code != 200:
                cycle["notes"].append("scenario_create_failed")
                cycles.append(cycle)
                continue

            scenario_payload = _safe_json(create_resp)
            scenario_id = int(scenario_payload.get("id") or 0)
            cycle["scenario_id"] = scenario_id
            scenarios_created.append(scenario_id)

            selected_variant: dict[str, Any] | None = None
            selected_preview: dict[str, Any] | None = None
            preview_status = None

            for attempt in range(0, 3):
                variant = _build_variant(i, preset, state_codes=state_codes, attempt=attempt)
                preview_resp = client.post(
                    f"/admin/scenarios/{scenario_id}/randomizer/preview",
                    headers=headers,
                    json=variant,
                )
                preview_status = int(preview_resp.status_code)
                cycle["randomizer_preview_status"] = preview_status

                if preview_resp.status_code != 200:
                    continue

                preview_payload = _safe_json(preview_resp)
                ratio = preview_payload.get("demand_ratio_vs_baseline")
                warning_count = len(preview_payload.get("guardrail_warnings") or [])

                in_band = _ratio_in_band(preset, (None if ratio is None else float(ratio)))
                if in_band and warning_count <= 200:
                    selected_variant = variant
                    selected_preview = preview_payload
                    break

                if attempt == 2:
                    selected_variant = variant
                    selected_preview = preview_payload
                    cycle["notes"].append("randomizer_preview_out_of_band")

            if selected_variant is None:
                cycle["notes"].append("randomizer_preview_failed")
                cycles.append(cycle)
                continue

            cycle["variant_used"] = selected_variant
            cycle["randomizer_demand_ratio"] = selected_preview.get("demand_ratio_vs_baseline") if selected_preview else None
            cycle["randomizer_row_count"] = selected_preview.get("row_count") if selected_preview else None
            cycle["randomizer_warning_count"] = len((selected_preview or {}).get("guardrail_warnings") or [])

            apply_resp = client.post(
                f"/admin/scenarios/{scenario_id}/randomizer/apply",
                headers=headers,
                json=selected_variant,
            )
            cycle["randomizer_apply_status"] = int(apply_resp.status_code)
            if apply_resp.status_code != 200:
                cycle["notes"].append("randomizer_apply_failed")
                cycles.append(cycle)
                continue

            run_resp = client.post(
                f"/admin/scenarios/{scenario_id}/run",
                headers=headers,
                json={"scope_mode": normalized_scope},
            )
            cycle["run_status"] = int(run_resp.status_code)

            if run_resp.status_code != 200:
                run_detail = _extract_failure_detail(run_resp)
                run_class = _classify_run_failure(run_resp.status_code, run_detail)
                cycle["run_failure_detail"] = run_detail
                cycle["run_failure_class"] = run_class
                cycle["notes"].append("scenario_run_failed")

                if run_class == "preflight":
                    cycle["run_retry_count"] = 1
                    cycle["notes"].append("preflight_retry_attempted")
                    retry_variant = _build_variant(i, preset, state_codes=state_codes, attempt=99)

                    retry_apply = client.post(
                        f"/admin/scenarios/{scenario_id}/randomizer/apply",
                        headers=headers,
                        json=retry_variant,
                    )
                    if retry_apply.status_code == 200:
                        retry_run = client.post(
                            f"/admin/scenarios/{scenario_id}/run",
                            headers=headers,
                            json={"scope_mode": normalized_scope},
                        )
                        cycle["run_status"] = int(retry_run.status_code)
                        if retry_run.status_code == 200:
                            cycle["run_failure_detail"] = None
                            cycle["run_failure_class"] = None
                            cycle["notes"] = [n for n in cycle["notes"] if n != "scenario_run_failed"]
                            cycle["notes"].append("preflight_retry_recovered")
                        else:
                            cycle["run_failure_detail"] = _extract_failure_detail(retry_run)
                            cycle["run_failure_class"] = _classify_run_failure(retry_run.status_code, cycle["run_failure_detail"])
                            cycle["notes"].append("preflight_retry_failed")
                    else:
                        cycle["notes"].append("preflight_retry_apply_failed")

            runs_resp = client.get(f"/admin/scenarios/{scenario_id}/runs", headers=headers)
            cycle["runs_list_status"] = int(runs_resp.status_code)
            runs = runs_resp.json() if runs_resp.status_code == 200 else []
            if runs:
                cycle["run_id"] = int((runs[0] or {}).get("id") or 0)
            else:
                cycle["notes"].append("no_run_id")

            if cycle["run_id"]:
                run_id = int(cycle["run_id"])

                summary_resp = client.get(
                    f"/admin/scenarios/{scenario_id}/runs/{run_id}/summary",
                    headers=headers,
                )
                cycle["summary_status"] = int(summary_resp.status_code)
                if summary_resp.status_code != 200:
                    cycle["notes"].append("run_summary_failed")

                revert_resp = client.post(
                    f"/admin/scenarios/{scenario_id}/revert-effects",
                    headers=headers,
                    json={"run_id": run_id},
                )
                cycle["revert_status"] = int(revert_resp.status_code)
                if revert_resp.status_code != 200:
                    cycle["notes"].append("revert_failed")

                verify_resp = client.get(
                    f"/admin/scenarios/{scenario_id}/revert-effects/verify?run_id={run_id}",
                    headers=headers,
                )
                cycle["verify_status"] = int(verify_resp.status_code)
                if verify_resp.status_code == 200:
                    verify_payload = _safe_json(verify_resp)
                    cycle["verify_ok"] = bool(verify_payload.get("ok"))
                    cycle["verify_net_total"] = verify_payload.get("net_total")
                    cycle["verify_debit_total"] = verify_payload.get("debit_total")
                    cycle["verify_revert_total"] = verify_payload.get("revert_total")
                    if not cycle["verify_ok"]:
                        cycle["notes"].append("revert_verify_not_zero")
                else:
                    cycle["notes"].append("revert_verify_failed")

            cycle["pass"] = (
                cycle.get("create_status") == 200
                and cycle.get("randomizer_apply_status") == 200
                and cycle.get("run_status") == 200
                and cycle.get("summary_status") == 200
                and cycle.get("revert_status") == 200
                and cycle.get("verify_status") == 200
                and cycle.get("verify_ok") is True
            )

            if not cycle["pass"] and not cycle["notes"]:
                cycle["notes"].append("unknown_failure")

        except Exception as exc:
            cycle["notes"].append(f"unexpected_exception:{type(exc).__name__}")
            cycle["notes"].append(str(exc))
        finally:
            cycle["finished_at"] = _now()
            cycles.append(cycle)

    pass_count = sum(1 for c in cycles if bool(c.get("pass")))
    fail_count = len(cycles) - pass_count

    return {
        "generated_at": _now(),
        "run_scope": normalized_scope,
        "target_runs": run_count,
        "executed_runs": len(cycles),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "overall_status": "PASS" if fail_count == 0 else "FAIL",
        "scenarios_created": scenarios_created,
        "cycles": cycles,
    }


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    json_path, md_path = _report_paths()
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Admin Scenario Certification Report",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Overall Status: **{report.get('overall_status')}**",
        f"Runs: {report.get('executed_runs')} (Pass={report.get('pass_count')}, Fail={report.get('fail_count')})",
        "",
        "## Cycle Results",
        "",
        "| Cycle | Scenario ID | Preset | Run ID | Run | Verify | Net Total | Result | Notes |",
        "|---:|---:|---|---:|---:|---|---:|---|---|",
    ]

    for c in report.get("cycles", []):
        lines.append(
            "| {cycle} | {scenario_id} | {preset} | {run_id} | {run_status} | {verify_ok} | {net_total} | {result} | {notes} |".format(
                cycle=c.get("cycle") or 0,
                scenario_id=c.get("scenario_id") or 0,
                preset=c.get("preset") or "-",
                run_id=c.get("run_id") or 0,
                run_status=c.get("run_status") or 0,
                verify_ok=("YES" if c.get("verify_ok") else "NO"),
                net_total=(c.get("verify_net_total") if c.get("verify_net_total") is not None else 0),
                result=("PASS" if c.get("pass") else "FAIL"),
                notes=(", ".join(c.get("notes") or []) or "-"),
            )
        )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Admin scenario certification run")
    parser.add_argument("--runs", type=int, default=30, help="Target runs (clamped to 10-30)")
    parser.add_argument("--run-scope", type=str, default="focused", choices=["focused", "full"], help="Scenario run scope for performance: focused|full")
    args = parser.parse_args()

    report = run_certification(target_runs=int(args.runs), run_scope=str(args.run_scope))
    json_path, md_path = write_reports(report)

    print(
        json.dumps(
            {
                "overall_status": report.get("overall_status"),
                "executed_runs": report.get("executed_runs"),
                "pass_count": report.get("pass_count"),
                "fail_count": report.get("fail_count"),
                "json_report": str(json_path),
                "md_report": str(md_path),
            }
        )
    )


if __name__ == "__main__":
    main()
