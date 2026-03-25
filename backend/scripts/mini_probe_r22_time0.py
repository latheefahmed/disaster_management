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


DISTRICT_CODE = "603"
TIME_IDX = 0
MAX_WAIT = 240
Q_LIST = [87000.0, 88500.0, 90000.0, 92000.0, 95000.0, 100000.0]


def wait_run(db, run_id):
    s = time.time()
    while time.time() - s < MAX_WAIT:
        db.expire_all()
        r = db.query(SolverRun).filter(SolverRun.id == int(run_id)).first()
        if r is None:
            return "missing"
        st = str(r.status or "").lower()
        if st in {"completed", "failed", "failed_reconciliation"}:
            return st
        time.sleep(1.2)
    return "timeout"


def summarize(db, req_id):
    rows = db.query(Allocation).filter(Allocation.request_id == int(req_id)).all()
    out = {"district": 0.0, "state": 0.0, "neighbor_state": 0.0, "national": 0.0, "unmet": 0.0}
    groups = {}
    neighbors = set()
    for r in rows:
        q = float(r.allocated_quantity or 0.0)
        if bool(r.is_unmet):
            out["unmet"] += q
            continue
        scope = str(r.allocation_source_scope or r.supply_level or "district").lower().strip()
        if scope not in out:
            scope = "district"
        out[scope] += q
        code = str(r.allocation_source_code or r.origin_state_code or r.state_code or "")
        groups[(scope, code)] = float(groups.get((scope, code), 0.0)) + q
        if scope == "neighbor_state" and code:
            neighbors.add(code)
    out["neighbor_count"] = len(neighbors)
    out["neighbors"] = sorted(neighbors)
    out["allocated_total"] = out["district"] + out["state"] + out["neighbor_state"] + out["national"]
    out["groups"] = groups
    return out


def do_return(db, user, run_id, rid, summary):
    if summary["allocated_total"] <= 1e-6:
        return 0.0
    claim_qty = int(math.floor(summary["allocated_total"] + 1e-6)) if requires_integer_quantity(rid) else float(summary["allocated_total"])
    create_claim(
        db=db,
        district_code=user["district_code"],
        resource_id=rid,
        time=TIME_IDX,
        quantity=float(claim_qty),
        claimed_by="district_manager",
        solver_run_id=run_id,
    )
    total = 0.0
    for (scope, code), q in summary["groups"].items():
        if float(q) <= 1e-9:
            continue
        rq = int(math.floor(q + 1e-6)) if requires_integer_quantity(rid) else float(q)
        if float(rq) <= 0:
            continue
        create_return(
            db=db,
            district_code=user["district_code"],
            state_code=user["state_code"],
            resource_id=rid,
            time=TIME_IDX,
            quantity=float(rq),
            reason="manual",
            solver_run_id=run_id,
            allocation_source_scope=scope,
            allocation_source_code=(code or None),
        )
        total += float(rq)
    return total


def main():
    db = SessionLocal()
    try:
        district = db.query(District).filter(District.district_code == DISTRICT_CODE).first()
        user = {"district_code": str(district.district_code), "state_code": str(district.state_code), "role": "district"}
        out = []
        for qty in Q_LIST:
            req = RequestCreate(resource_id="R22", time=TIME_IDX, quantity=float(qty), priority=5, urgency=5, confidence=1.0, source="human")
            created = create_request(db, user, req)
            req_id = int(created["request_id"])
            run_id = int(created["solver_run_id"])
            run_status = wait_run(db, run_id)
            _ = get_district_requests_view(db, user["district_code"], latest_only=False, limit=10, offset=0)
            rrow = db.query(ResourceRequest).filter(ResourceRequest.id == req_id).first()
            s = summarize(db, req_id)
            returned = do_return(db, user, run_id, "R22", s)
            out.append({
                "qty": qty,
                "request_id": req_id,
                "run_id": run_id,
                "run_status": run_status,
                "request_status": str(rrow.status if rrow else "missing"),
                "district": s["district"],
                "state": s["state"],
                "interstate": s["neighbor_state"],
                "national": s["national"],
                "unmet": s["unmet"],
                "neighbor_count": s["neighbor_count"],
                "neighbors": s["neighbors"],
                "returned": returned,
            })
        print(json.dumps(out, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
