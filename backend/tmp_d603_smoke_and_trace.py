from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import requests

from app.database import SessionLocal
from app.models.allocation import Allocation
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun

BASE = "http://127.0.0.1:8000"
OUT = Path("D603_SMOKE_TRACE_REPORT_2026-03-05.json")


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def login(username: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=30)
    r.raise_for_status()
    return str(r.json().get("access_token") or "")


def get_json(path: str, token: str):
    r = requests.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def post_json(path: str, token: str, payload: dict):
    r = requests.post(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=60)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    return r.status_code, body


def wait_run(run_id: int, timeout_s: int = 240):
    started = time.time()
    while time.time() - started < timeout_s:
        with SessionLocal() as db:
            row = db.query(SolverRun).filter(SolverRun.id == int(run_id)).first()
            if row is not None:
                status = str(row.status or "")
                if status.lower() in {"completed", "failed", "failed_reconciliation"}:
                    return {
                        "solver_run_id": int(row.id),
                        "status": status,
                        "started_at": str(row.started_at),
                        "summary_snapshot_json": str(getattr(row, "summary_snapshot_json", "") or ""),
                    }
        time.sleep(2)
    return {"solver_run_id": int(run_id), "status": "timeout"}


def main() -> None:
    report = {
        "started_at": now_iso(),
        "base": BASE,
    }

    token = login("district_603", "district123")

    resources = requests.get(f"{BASE}/metadata/resources", timeout=30).json()
    by_name = {str(r.get("resource_name") or "").lower(): str(r.get("resource_id") or "") for r in resources}

    # Include medical kits + oxygen cylinders explicitly, then fill to ~8 resources.
    preferred_names = [
        "medical_kits",
        "oxygen_cylinders",
        "food_packets",
        "drinking_water_litres",
        "blankets",
        "ppe_kits",
        "first_aid_kits",
        "family_shelter_kits",
    ]
    resource_ids: list[str] = []
    for name in preferred_names:
        rid = by_name.get(name)
        if rid and rid not in resource_ids:
            resource_ids.append(rid)
    for r in resources:
        rid = str(r.get("resource_id") or "")
        if rid and rid not in resource_ids:
            resource_ids.append(rid)
        if len(resource_ids) >= 8:
            break
    resource_ids = resource_ids[:8]

    qtys = [25, 80, 150, 260, 400, 75, 120, 90]
    items = []
    for idx, rid in enumerate(resource_ids):
        items.append({
            "resource_id": rid,
            "quantity": float(qtys[idx % len(qtys)]),
            "time": int(idx % 4),
            "source": "human",
        })

    # Explicit medical kits smoke request if available.
    med_id = by_name.get("medical_kits")
    if med_id and med_id not in [x["resource_id"] for x in items]:
        items.append({"resource_id": med_id, "quantity": 111.0, "time": 1, "source": "human"})

    code, body = post_json("/district/request-batch", token, {"items": items})
    report["request_batch"] = {"status_code": code, "response": body, "items": items}

    run_id = int((body or {}).get("solver_run_id") or 0)
    run_result = wait_run(run_id) if run_id > 0 else {"solver_run_id": run_id, "status": "missing"}
    report["run_result"] = run_result

    requests_rows = get_json("/district/requests?page=1&page_size=200", token)
    report["latest_requests_sample"] = requests_rows[:30] if isinstance(requests_rows, list) else []

    alloc_rows = get_json("/district/allocations?page=1&page_size=200", token)
    report["latest_allocations_sample"] = alloc_rows[:30] if isinstance(alloc_rows, list) else []

    ordering_ok = True
    if isinstance(alloc_rows, list) and len(alloc_rows) >= 2:
        prev = alloc_rows[0]
        for cur in alloc_rows[1:]:
            if int(cur.get("solver_run_id") or 0) > int(prev.get("solver_run_id") or 0):
                ordering_ok = False
                break
            prev = cur
    report["alloc_order_latest_first"] = bool(ordering_ok)

    # Trace oxygen cylinders request around quantity 50001 in district 603.
    oxygen_id = by_name.get("oxygen_cylinders")
    oxygen_trace = {}
    if oxygen_id:
        with SessionLocal() as db:
            target_req = db.query(ResourceRequest).filter(
                ResourceRequest.district_code == "603",
                ResourceRequest.resource_id == oxygen_id,
                ResourceRequest.quantity >= 50001,
            ).order_by(ResourceRequest.id.desc()).first()

            if target_req is not None:
                slot_rows = db.query(Allocation).filter(
                    Allocation.solver_run_id == int(target_req.run_id or 0),
                    Allocation.district_code == str(target_req.district_code),
                    Allocation.resource_id == str(target_req.resource_id),
                    Allocation.time == int(target_req.time),
                    Allocation.is_unmet == False,
                ).all()
                totals = {"district": 0.0, "state": 0.0, "neighbor_state": 0.0, "national": 0.0, "unknown": 0.0}
                for row in slot_rows:
                    scope = str(getattr(row, "allocation_source_scope", "") or getattr(row, "supply_level", "district") or "district").lower()
                    qty = float(getattr(row, "allocated_quantity", 0.0) or 0.0)
                    if scope not in totals:
                        scope = "unknown"
                    totals[scope] += qty

                oxygen_trace = {
                    "request_id": int(target_req.id),
                    "resource_id": str(target_req.resource_id),
                    "quantity": float(target_req.quantity or 0.0),
                    "time": int(target_req.time or 0),
                    "status": str(target_req.status or ""),
                    "run_id": int(target_req.run_id or 0),
                    "allocated_quantity": float(target_req.allocated_quantity or 0.0),
                    "unmet_quantity": float(target_req.unmet_quantity or 0.0),
                    "source_breakdown": totals,
                }
            else:
                oxygen_trace = {"note": "No district_603 oxygen_cylinders request with quantity >= 50001 found."}
    report["oxygen_50001_trace"] = oxygen_trace

    report["finished_at"] = now_iso()
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "report_file": str(OUT),
        "run_result": report.get("run_result"),
        "alloc_order_latest_first": report.get("alloc_order_latest_first"),
        "oxygen_50001_trace": report.get("oxygen_50001_trace"),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
