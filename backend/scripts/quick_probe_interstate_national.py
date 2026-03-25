import json
import math
import time

from app.database import SessionLocal
from app.models.allocation import Allocation
from app.models.district import District
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.schemas.request import RequestCreate
from app.services.action_service import create_claim, create_return
from app.services.canonical_resources import requires_integer_quantity
from app.services.request_service import create_request, get_district_requests_view
from app.services.resource_policy import is_resource_consumable, is_resource_returnable


DISTRICT_CODE = "603"
TIME_SLOT = 0
MAX_WAIT = 240

# Short, non-exhaustive probes from recent behavior.
PROBES = [
    {"resource_id": "R33", "quantity": 2500.0, "label": "interstate_target_R33_2500"},
    {"resource_id": "R22", "quantity": 100000.0, "label": "national_target_R22_100000"},
    {"resource_id": "R33", "quantity": 40000.0, "label": "national_alt_R33_40000"},
]


def wait_completed(db, run_id: int) -> str:
    start = time.time()
    while time.time() - start < MAX_WAIT:
        db.expire_all()
        row = db.query(SolverRun).filter(SolverRun.id == int(run_id)).first()
        if row is None:
            return "missing"
        status = str(row.status or "").lower()
        if status in {"completed", "failed", "failed_reconciliation"}:
            return status
        time.sleep(1.5)
    return "timeout"


def summarize(db, request_id: int) -> dict:
    rows = db.query(Allocation).filter(Allocation.request_id == int(request_id)).all()
    scopes = {"district": 0.0, "state": 0.0, "neighbor_state": 0.0, "national": 0.0}
    groups = {}
    neighbors = set()
    unmet = 0.0

    for r in rows:
        qty = float(r.allocated_quantity or 0.0)
        if bool(r.is_unmet):
            unmet += qty
            continue
        scope = str(r.allocation_source_scope or r.supply_level or "district").strip().lower()
        if scope not in scopes:
            scope = "district"
        scopes[scope] += qty
        code = str(r.allocation_source_code or r.origin_state_code or r.state_code or "")
        key = (scope, code)
        groups[key] = float(groups.get(key, 0.0)) + qty
        if scope == "neighbor_state" and code:
            neighbors.add(code)

    present = sorted([k for k, v in scopes.items() if float(v) > 1e-6])
    return {
        "scopes": scopes,
        "present_scopes": present,
        "neighbor_states": sorted(neighbors),
        "neighbor_state_count": len(neighbors),
        "unmet": unmet,
        "source_groups": groups,
        "allocated_total": sum(float(v) for v in scopes.values()),
    }


def do_return(db, user: dict, rid: str, run_id: int, summary: dict) -> float:
    if summary["allocated_total"] <= 1e-9:
        return 0.0
    if not is_resource_returnable(rid) or is_resource_consumable(rid):
        return 0.0

    total = 0.0
    integer_only = bool(requires_integer_quantity(rid))
    source_items = [
        ((scope, code), float(qty))
        for (scope, code), qty in summary["source_groups"].items()
        if float(qty) > 1e-9
    ]

    if integer_only:
        claim_qty = int(math.floor(float(summary["allocated_total"]) + 1e-6))
        if claim_qty > 0:
            create_claim(
                db=db,
                district_code=user["district_code"],
                resource_id=rid,
                time=TIME_SLOT,
                quantity=float(claim_qty),
                claimed_by="district_manager",
                solver_run_id=run_id,
            )
        floor_parts = []
        total_floor = 0
        for key, raw in source_items:
            base = int(math.floor(raw + 1e-9))
            frac = float(raw - base)
            floor_parts.append((key, base, frac))
            total_floor += base
        rem = max(0, int(claim_qty - total_floor))
        floor_parts.sort(key=lambda x: x[2], reverse=True)
        adjusted = []
        for i, (key, base, _frac) in enumerate(floor_parts):
            adjusted.append((key, base + (1 if i < rem else 0)))
        for (scope, code), q_int in adjusted:
            q = float(q_int)
            if q <= 0:
                continue
            create_return(
                db=db,
                district_code=user["district_code"],
                state_code=user["state_code"],
                resource_id=rid,
                time=TIME_SLOT,
                quantity=q,
                reason="manual",
                solver_run_id=run_id,
                allocation_source_scope=scope,
                allocation_source_code=(code or None),
            )
            total += q
    else:
        claim_qty = float(summary["allocated_total"])
        create_claim(
            db=db,
            district_code=user["district_code"],
            resource_id=rid,
            time=TIME_SLOT,
            quantity=claim_qty,
            claimed_by="district_manager",
            solver_run_id=run_id,
        )
        for (scope, code), qty in source_items:
            q = float(qty)
            if q <= 1e-9:
                continue
            create_return(
                db=db,
                district_code=user["district_code"],
                state_code=user["state_code"],
                resource_id=rid,
                time=TIME_SLOT,
                quantity=q,
                reason="manual",
                solver_run_id=run_id,
                allocation_source_scope=scope,
                allocation_source_code=(code or None),
            )
            total += q

    return total


def main() -> None:
    db = SessionLocal()
    try:
        district = db.query(District).filter(District.district_code == DISTRICT_CODE).first()
        if district is None:
            raise RuntimeError("District 603 not found")
        user = {"district_code": str(district.district_code), "state_code": str(district.state_code), "role": "district"}

        results = []
        interstate_case = None
        national_case = None

        for p in PROBES:
            payload = RequestCreate(
                resource_id=str(p["resource_id"]),
                time=TIME_SLOT,
                quantity=float(p["quantity"]),
                priority=5,
                urgency=5,
                confidence=1.0,
                source="human",
            )
            resp = create_request(db, user, payload)
            request_id = int(resp["request_id"])
            run_id = int(resp["solver_run_id"])

            run_status = wait_completed(db, run_id)
            _ = get_district_requests_view(db, user["district_code"], latest_only=False, limit=10, offset=0)
            req = db.query(ResourceRequest).filter(ResourceRequest.id == request_id).first()
            req_status = str(req.status or "unknown") if req else "missing"

            summary = summarize(db, request_id)
            returned = do_return(db, user, str(p["resource_id"]), run_id, summary)

            row = {
                "label": p["label"],
                "resource_id": p["resource_id"],
                "quantity": float(p["quantity"]),
                "request_id": request_id,
                "solver_run_id": run_id,
                "run_status": run_status,
                "request_status": req_status,
                "present_scopes": summary["present_scopes"],
                "scope_totals": summary["scopes"],
                "neighbor_state_count": summary["neighbor_state_count"],
                "neighbor_states": summary["neighbor_states"],
                "unmet": summary["unmet"],
                "returned_total": float(returned),
            }
            results.append(row)

            scopes = set(summary["present_scopes"])
            if interstate_case is None and ("neighbor_state" in scopes) and ("national" not in scopes):
                interstate_case = row
            if national_case is None and ("national" in scopes):
                national_case = row
            if interstate_case is not None and national_case is not None:
                break

        out = {
            "district_code": DISTRICT_CODE,
            "time_slot": TIME_SLOT,
            "results": results,
            "interstate_case": interstate_case,
            "national_case": national_case,
        }

        out_path = "TARGETED_INTERSTATE_NATIONAL_PROBE.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)

        print(json.dumps({
            "out_path": out_path,
            "attempts": len(results),
            "interstate_case_found": interstate_case is not None,
            "national_case_found": national_case is not None,
            "interstate_case": interstate_case,
            "national_case": national_case,
        }, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
