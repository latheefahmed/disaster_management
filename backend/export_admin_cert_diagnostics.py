from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func

from app.main import app
from app.database import SessionLocal
from app.models.allocation import Allocation
from app.models.shipment_plan import ShipmentPlan
from app.models.solver_run import SolverRun


def _safe_json(resp) -> dict[str, Any]:
    try:
        payload = resp.json()
        return payload if isinstance(payload, dict) else {"payload": payload}
    except Exception:
        return {"raw": getattr(resp, "text", "")}


def main() -> None:
    root = Path(__file__).resolve().parent
    report_path = root / "ADMIN_SCENARIO_CERT_REPORT.json"
    out_path = root / "ADMIN_SCENARIO_CERT_ENRICHED_RUN_OBJECTS.json"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    cycles = list(report.get("cycles") or [])

    client = TestClient(app, raise_server_exceptions=False)
    login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    if login.status_code != 200:
        raise RuntimeError(f"Admin login failed: {login.status_code} {login.text}")

    token = login.json().get("access_token")
    if not token:
        raise RuntimeError("Missing access_token")

    headers = {"Authorization": f"Bearer {token}"}

    db = SessionLocal()
    try:
        enriched: list[dict[str, Any]] = []
        for cycle in cycles:
            scenario_id = int(cycle.get("scenario_id") or 0)
            run_id = int(cycle.get("run_id") or 0)

            run_row = db.query(SolverRun).filter(SolverRun.id == run_id).first() if run_id else None
            run_db_status = None if run_row is None else str(run_row.status)

            summary_obj: dict[str, Any] | None = None
            summary_resp_status: int | None = None
            if scenario_id and run_id:
                summary_resp = client.get(
                    f"/admin/scenarios/{scenario_id}/runs/{run_id}/summary",
                    headers=headers,
                )
                summary_resp_status = int(summary_resp.status_code)
                if summary_resp.status_code == 200:
                    summary_obj = _safe_json(summary_resp)

            allocation_scope_counts = {
                "district": 0,
                "state": 0,
                "neighbor_state": 0,
                "national": 0,
            }
            origin_state_count = 0
            if run_id:
                scope_rows = (
                    db.query(
                        Allocation.allocation_source_scope,
                        func.count(Allocation.id).label("count"),
                    )
                    .filter(Allocation.solver_run_id == int(run_id), Allocation.is_unmet == False)
                    .group_by(Allocation.allocation_source_scope)
                    .all()
                )
                for row in scope_rows:
                    key = str(row.allocation_source_scope or "district")
                    allocation_scope_counts[key] = int(row.count or 0)

                origin_state_count = int(
                    db.query(func.count(Allocation.id))
                    .filter(
                        Allocation.solver_run_id == int(run_id),
                        Allocation.is_unmet == False,
                        Allocation.origin_state_code.isnot(None),
                        func.trim(func.coalesce(Allocation.origin_state_code, "")) != "",
                    )
                    .scalar()
                    or 0
                )

            shipment_rows_total = (
                int(
                    db.query(func.count(ShipmentPlan.id))
                    .filter(ShipmentPlan.solver_run_id == int(run_id))
                    .scalar()
                    or 0
                )
                if run_id
                else 0
            )

            non_district_alloc_rows = (
                int(
                    db.query(func.count(Allocation.id))
                    .filter(
                        Allocation.solver_run_id == int(run_id),
                        Allocation.is_unmet == False,
                        Allocation.supply_level.in_(["state", "national"]),
                    )
                    .scalar()
                    or 0
                )
                if run_id
                else 0
            )

            enriched.append(
                {
                    "cycle": int(cycle.get("cycle") or 0),
                    "preset": cycle.get("preset"),
                    "scenario_id": scenario_id,
                    "scenario_name": cycle.get("scenario_name"),
                    "run_id": run_id,
                    "cert_status": {
                        "pass": bool(cycle.get("pass")),
                        "notes": list(cycle.get("notes") or []),
                        "run_status": cycle.get("run_status"),
                        "summary_status": cycle.get("summary_status"),
                        "revert_status": cycle.get("revert_status"),
                        "verify_status": cycle.get("verify_status"),
                        "verify_ok": cycle.get("verify_ok"),
                        "verify_net_total": cycle.get("verify_net_total"),
                        "verify_debit_total": cycle.get("verify_debit_total"),
                        "verify_revert_total": cycle.get("verify_revert_total"),
                    },
                    "scenario_run_db_status": run_db_status,
                    "summary_endpoint_status": summary_resp_status,
                    "summary": summary_obj,
                    "allocation_source_scope_counts": allocation_scope_counts,
                    "allocation_origin_state_rows": origin_state_count,
                    "non_district_allocation_rows": non_district_alloc_rows,
                    "shipment_rows": shipment_rows_total,
                    "shipment_expectation_note": (
                        "Shipment rows are expected only when ingest succeeded and non-district allocation rows exist"
                    ),
                    "timing": {
                        "started_at": cycle.get("started_at"),
                        "finished_at": cycle.get("finished_at"),
                    },
                }
            )

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_report": str(report_path),
            "target_runs": report.get("target_runs"),
            "executed_runs": report.get("executed_runs"),
            "pass_count": report.get("pass_count"),
            "fail_count": report.get("fail_count"),
            "overall_status": report.get("overall_status"),
            "run_objects": enriched,
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(out_path), "runs": len(enriched)}))
    finally:
        db.close()


if __name__ == "__main__":
    main()
