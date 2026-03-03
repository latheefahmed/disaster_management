from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app


PRESETS = ["very_low", "low", "medium", "high", "extreme"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(resp) -> dict[str, Any]:
    try:
        payload = resp.json()
        return payload if isinstance(payload, dict) else {"payload": payload}
    except Exception:
        return {"raw": getattr(resp, "text", "")}


def _report_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parent
    return (
        root / "ADMIN_DASHBOARD_SMOKE_REPORT.json",
        root / "ADMIN_DASHBOARD_SMOKE_REPORT.md",
    )


def run_smoke_suite() -> dict[str, Any]:
    client = TestClient(app, raise_server_exceptions=False)
    checks: list[dict[str, Any]] = []

    login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    checks.append({"check": "login_admin", "ok": login.status_code == 200, "status": login.status_code})
    if login.status_code != 200:
        return {
            "generated_at": _now(),
            "overall_status": "FAIL",
            "checks": checks,
            "summary": {"passed": sum(1 for c in checks if c.get("ok")), "failed": sum(1 for c in checks if not c.get("ok"))},
        }

    token = _safe_json(login).get("access_token")
    headers = {"Authorization": f"Bearer {token}"}

    list_resp = client.get("/admin/scenarios", headers=headers)
    checks.append({"check": "list_scenarios", "ok": list_resp.status_code == 200, "status": list_resp.status_code})

    create_resp = client.post("/admin/scenarios", headers=headers, json={"name": f"AUTO_SMOKE_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"})
    create_payload = _safe_json(create_resp)
    scenario_id = int(create_payload.get("id") or 0)
    checks.append({
        "check": "create_scenario",
        "ok": create_resp.status_code == 200 and scenario_id > 0,
        "status": create_resp.status_code,
        "scenario_id": scenario_id,
    })

    if scenario_id <= 0:
        return {
            "generated_at": _now(),
            "overall_status": "FAIL",
            "checks": checks,
            "summary": {"passed": sum(1 for c in checks if c.get("ok")), "failed": sum(1 for c in checks if not c.get("ok"))},
        }

    # Five preset checks for randomizer preview (different dashboard presets)
    for idx, preset in enumerate(PRESETS, start=1):
        preview_payload = {
            "preset": preset,
            "seed": 20271000 + idx,
            "time_horizon": 3 + (idx % 3),
            "district_count": 10 + idx,
            "resource_count": 5 + idx,
            "stress_mode": True,
            "replace_existing": True,
        }
        preview_resp = client.post(
            f"/admin/scenarios/{scenario_id}/randomizer/preview",
            headers=headers,
            json=preview_payload,
        )
        preview_json = _safe_json(preview_resp)
        checks.append(
            {
                "check": f"preview_{preset}",
                "ok": preview_resp.status_code == 200 and int(preview_json.get("row_count") or 0) > 0,
                "status": preview_resp.status_code,
                "row_count": int(preview_json.get("row_count") or 0),
                "ratio": preview_json.get("demand_ratio_vs_baseline"),
            }
        )

    apply_payload = {
        "preset": "high",
        "seed": 20279991,
        "time_horizon": 5,
        "district_count": 20,
        "resource_count": 10,
        "stress_mode": True,
        "replace_existing": True,
    }
    apply_resp = client.post(
        f"/admin/scenarios/{scenario_id}/randomizer/apply",
        headers=headers,
        json=apply_payload,
    )
    apply_json = _safe_json(apply_resp)
    checks.append(
        {
            "check": "apply_randomizer",
            "ok": apply_resp.status_code == 200 and int(apply_json.get("applied_rows") or 0) > 0,
            "status": apply_resp.status_code,
            "applied_rows": int(apply_json.get("applied_rows") or 0),
        }
    )

    run_resp = client.post(
        f"/admin/scenarios/{scenario_id}/run",
        headers=headers,
        json={"scope_mode": "focused"},
    )
    checks.append({"check": "run_scenario", "ok": run_resp.status_code == 200, "status": run_resp.status_code})

    runs_resp = client.get(f"/admin/scenarios/{scenario_id}/runs", headers=headers)
    runs_arr = runs_resp.json() if runs_resp.status_code == 200 else []
    run_id = int((runs_arr[0] or {}).get("id") or 0) if runs_arr else 0
    checks.append(
        {
            "check": "list_runs_and_pick_run_id",
            "ok": runs_resp.status_code == 200 and run_id > 0,
            "status": runs_resp.status_code,
            "run_id": run_id,
        }
    )

    summary_resp = client.get(f"/admin/scenarios/{scenario_id}/runs/{run_id}/summary", headers=headers)
    summary_json = _safe_json(summary_resp)

    by_time = list(summary_json.get("by_time_breakdown") or [])
    scope = summary_json.get("source_scope_breakdown") or {}
    fairness = summary_json.get("fairness") or {}
    scope_alloc = scope.get("allocations") or {}

    checks.append(
        {
            "check": "summary_has_by_time_breakdown",
            "ok": summary_resp.status_code == 200 and len(by_time) > 0,
            "status": summary_resp.status_code,
            "by_time_rows": len(by_time),
        }
    )
    checks.append(
        {
            "check": "summary_has_scope_breakdown",
            "ok": all(k in scope_alloc for k in ["district", "state", "neighbor_state", "national"]),
            "scope_keys": sorted(list(scope_alloc.keys())),
        }
    )
    checks.append(
        {
            "check": "summary_has_fairness_diagnostics",
            "ok": isinstance(fairness.get("fairness_flags"), list),
            "flags": fairness.get("fairness_flags") or [],
            "early_avg": fairness.get("time_service_early_avg"),
            "late_avg": fairness.get("time_service_late_avg"),
        }
    )

    incidents_resp = client.get(
        f"/admin/scenarios/{scenario_id}/runs/incidents?limit=40",
        headers=headers,
    )
    incidents_json = _safe_json(incidents_resp)
    incident_rows = list(incidents_json.get("incidents") or []) if isinstance(incidents_json, dict) else []
    checks.append(
        {
            "check": "incidents_endpoint_available",
            "ok": incidents_resp.status_code == 200,
            "status": incidents_resp.status_code,
            "incident_count": incidents_json.get("incident_count") if isinstance(incidents_json, dict) else None,
        }
    )
    checks.append(
        {
            "check": "incidents_payload_shape",
            "ok": isinstance(incident_rows, list),
            "incident_rows": len(incident_rows),
        }
    )

    revert_resp = client.post(
        f"/admin/scenarios/{scenario_id}/revert-effects",
        headers=headers,
        json={"run_id": run_id},
    )
    checks.append({"check": "revert_run_effects", "ok": revert_resp.status_code == 200, "status": revert_resp.status_code})

    verify_resp = client.get(
        f"/admin/scenarios/{scenario_id}/revert-effects/verify?run_id={run_id}",
        headers=headers,
    )
    verify_json = _safe_json(verify_resp)
    checks.append(
        {
            "check": "verify_revert_balance",
            "ok": verify_resp.status_code == 200 and bool(verify_json.get("ok")) is True,
            "status": verify_resp.status_code,
            "net_total": verify_json.get("net_total"),
        }
    )

    passed = sum(1 for c in checks if bool(c.get("ok")))
    failed = len(checks) - passed
    return {
        "generated_at": _now(),
        "scenario_id": scenario_id,
        "run_id": run_id,
        "overall_status": "PASS" if failed == 0 else "FAIL",
        "summary": {
            "passed": passed,
            "failed": failed,
            "checks_total": len(checks),
            "preset_checks": len(PRESETS),
        },
        "checks": checks,
    }


def write_report(report: dict[str, Any]) -> tuple[Path, Path]:
    json_path, md_path = _report_paths()
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Admin Dashboard Smoke Report",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Overall: **{report.get('overall_status')}**",
        f"Scenario ID: {report.get('scenario_id')}",
        f"Run ID: {report.get('run_id')}",
        f"Checks: {((report.get('summary') or {}).get('checks_total'))} | Pass: {((report.get('summary') or {}).get('passed'))} | Fail: {((report.get('summary') or {}).get('failed'))}",
        "",
        "| Check | Pass | Details |",
        "|---|---|---|",
    ]

    for c in report.get("checks", []):
        details = []
        for key in ["status", "row_count", "ratio", "applied_rows", "run_id", "by_time_rows", "scope_keys", "flags", "net_total"]:
            if key in c:
                details.append(f"{key}={c.get(key)}")
        lines.append(f"| {c.get('check')} | {'PASS' if c.get('ok') else 'FAIL'} | {'; '.join(details) or '-'} |")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    report = run_smoke_suite()
    json_path, md_path = write_report(report)
    print(
        json.dumps(
            {
                "overall_status": report.get("overall_status"),
                "checks_total": (report.get("summary") or {}).get("checks_total"),
                "passed": (report.get("summary") or {}).get("passed"),
                "failed": (report.get("summary") or {}).get("failed"),
                "json_report": str(json_path),
                "md_report": str(md_path),
            }
        )
    )


if __name__ == "__main__":
    main()
