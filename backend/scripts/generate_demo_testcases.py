import json
import math
import time
from dataclasses import dataclass, asdict

from app.database import SessionLocal
from app.models.district import District
from app.models.solver_run import SolverRun
from app.models.allocation import Allocation
from app.schemas.request import RequestCreate
from app.services.request_service import create_request, get_district_requests_view
from app.services.action_service import create_claim, create_return
from app.services.kpi_service import get_district_stock_rows
from app.services.resource_policy import is_resource_returnable, is_resource_consumable
from app.services.canonical_resources import (
    CANONICAL_RESOURCE_ORDER,
    CANONICAL_RESOURCE_NAME,
    requires_integer_quantity,
    max_quantity_for,
)


DISTRICT_CODE = "603"
TIME_SLOT = 0
MAX_WAIT_SEC = 240


@dataclass
class CaseResult:
    case_name: str
    resource_id: str
    resource_name: str
    quantity: float
    request_id: int
    solver_run_id: int
    request_status: str
    scope_totals: dict
    neighbor_states: list
    neighbor_state_count: int
    allocated_total: float
    unmet_total: float
    returned_total: float


def wait_run_completed(db, run_id: int, timeout_sec: int = MAX_WAIT_SEC) -> str:
    start = time.time()
    last_status = "running"
    while time.time() - start < timeout_sec:
        db.expire_all()
        row = db.query(SolverRun).filter(SolverRun.id == int(run_id)).first()
        if row is None:
            return "missing"
        last_status = str(row.status or "").lower()
        if last_status in {"completed", "failed", "failed_reconciliation"}:
            return last_status
        time.sleep(1.5)
    return f"timeout:{last_status}"


def summarize_request_allocations(db, request_id: int) -> dict:
    rows = db.query(Allocation).filter(
        Allocation.request_id == int(request_id),
        Allocation.is_unmet == False,
    ).all()

    unmet_rows = db.query(Allocation).filter(
        Allocation.request_id == int(request_id),
        Allocation.is_unmet == True,
    ).all()

    scope_totals = {
        "district": 0.0,
        "state": 0.0,
        "neighbor_state": 0.0,
        "national": 0.0,
    }
    source_groups = {}
    neighbor_states = set()

    for r in rows:
        scope = str(r.allocation_source_scope or r.supply_level or "district").strip().lower()
        if scope not in scope_totals:
            scope = "district"
        qty = float(r.allocated_quantity or 0.0)
        scope_totals[scope] += qty

        code = str(r.allocation_source_code or "").strip()
        if not code:
            if scope == "district":
                code = str(r.district_code or "")
            elif scope in {"state", "neighbor_state"}:
                code = str(r.origin_state_code or r.state_code or "")
            elif scope == "national":
                code = "NATIONAL"

        key = (scope, code)
        source_groups[key] = float(source_groups.get(key, 0.0)) + qty

        if scope == "neighbor_state":
            state_code = str(r.origin_state_code or code or "").strip()
            if state_code and state_code.upper() != "NATIONAL":
                neighbor_states.add(state_code)

    unmet_total = float(sum(float(r.allocated_quantity or 0.0) for r in unmet_rows))
    allocated_total = float(sum(float(v) for v in scope_totals.values()))

    return {
        "scope_totals": scope_totals,
        "source_groups": source_groups,
        "neighbor_states": sorted(neighbor_states),
        "neighbor_state_count": len(neighbor_states),
        "allocated_total": allocated_total,
        "unmet_total": unmet_total,
    }


def pattern_of(summary: dict) -> set:
    out = set()
    for k, v in summary["scope_totals"].items():
        if float(v) > 1e-6:
            out.add(k)
    return out


def matches_pattern(target: str, summary: dict) -> bool:
    scopes = pattern_of(summary)
    neighbors = int(summary["neighbor_state_count"])

    has_d = "district" in scopes
    has_s = "state" in scopes
    has_i = "neighbor_state" in scopes
    has_n = "national" in scopes

    if target == "district_only":
        return has_d and not has_s and not has_i and not has_n
    if target == "district_state":
        return has_d and has_s and not has_i and not has_n
    if target == "district_state_interstate":
        return has_d and has_s and has_i and not has_n
    if target == "district_state_interstate_national":
        return has_d and has_s and has_i and has_n
    if target == "district_state_interstate_two":
        return has_d and has_s and has_i and not has_n and neighbors == 2
    return False


def propose_quantities(d: float, s: float, n: float) -> list[float]:
    vals = []
    vals += [max(1.0, math.floor(max(1.0, d * x))) for x in [0.35, 0.55, 0.75, 0.9]]
    vals += [max(1.0, math.floor(d + y)) for y in [1, max(2.0, 0.15 * max(1.0, s)), max(3.0, 0.45 * max(1.0, s)), max(4.0, 0.9 * max(1.0, s))]]
    vals += [max(1.0, math.floor(d + s + z)) for z in [10, max(10.0, 0.1 * max(1.0, n)), max(20.0, 0.35 * max(1.0, n)), max(30.0, 0.7 * max(1.0, n)), max(40.0, 1.2 * max(1.0, n)), max(50.0, 2.0 * max(1.0, n))]]
    # De-duplicate while preserving order
    seen = set()
    out = []
    for q in vals:
        qi = float(int(max(1.0, round(q))))
        if qi not in seen:
            seen.add(qi)
            out.append(qi)
    return out


def execute_request_and_optional_return(db, user: dict, rid: str, qty: float) -> tuple[dict, dict]:
    payload = RequestCreate(
        resource_id=rid,
        time=TIME_SLOT,
        quantity=float(qty),
        priority=5,
        urgency=5,
        confidence=1.0,
        source="human",
    )
    resp = create_request(db, user, payload)
    req_id = int(resp["request_id"])
    run_id = int(resp["solver_run_id"])

    run_status = wait_run_completed(db, run_id)
    # Force status refresh path used by UI.
    _ = get_district_requests_view(db, user["district_code"], latest_only=False, limit=10, offset=0)

    req_status = "unknown"
    from app.models.request import ResourceRequest
    req_row = db.query(ResourceRequest).filter(ResourceRequest.id == req_id).first()
    if req_row is not None:
        req_status = str(req_row.status or "unknown")

    summary = summarize_request_allocations(db, req_id)
    summary["request_id"] = req_id
    summary["solver_run_id"] = run_id
    summary["run_status"] = run_status
    summary["request_status"] = req_status

    returned_total = 0.0
    if summary["allocated_total"] > 1e-9 and is_resource_returnable(rid) and not is_resource_consumable(rid):
        try:
            integer_only = bool(requires_integer_quantity(rid))
            source_items = [((scope, code), float(qty_v)) for (scope, code), qty_v in summary["source_groups"].items() if float(qty_v) > 1e-9]

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

                # Integer-safe source split: floor each source then distribute remainder by largest fractional parts.
                floor_parts = []
                total_floor = 0
                for key, raw_q in source_items:
                    base = int(math.floor(raw_q + 1e-9))
                    frac = float(raw_q - base)
                    floor_parts.append((key, base, frac))
                    total_floor += base

                remainder = max(0, int(claim_qty - total_floor))
                floor_parts.sort(key=lambda x: x[2], reverse=True)
                adjusted = []
                for idx, (key, base, frac) in enumerate(floor_parts):
                    extra = 1 if idx < remainder else 0
                    adjusted.append((key, base + extra))

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
                    returned_total += q
            else:
                create_claim(
                    db=db,
                    district_code=user["district_code"],
                    resource_id=rid,
                    time=TIME_SLOT,
                    quantity=float(summary["allocated_total"]),
                    claimed_by="district_manager",
                    solver_run_id=run_id,
                )

                for (scope, code), source_qty in source_items:
                    q = float(source_qty)
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
                    returned_total += q
        except Exception as exc:
            summary["return_error"] = str(exc)

    summary["returned_total"] = returned_total
    return resp, summary


def main():
    db = SessionLocal()
    try:
        district = db.query(District).filter(District.district_code == DISTRICT_CODE).first()
        if district is None:
            raise RuntimeError(f"District {DISTRICT_CODE} not found")
        user = {
            "district_code": str(district.district_code),
            "state_code": str(district.state_code),
            "role": "district",
        }

        stock_rows = get_district_stock_rows(db, DISTRICT_CODE)
        stock_map = {str(r["resource_id"]): r for r in stock_rows}

        candidates = []
        for rid in CANONICAL_RESOURCE_ORDER:
            if not is_resource_returnable(rid) or is_resource_consumable(rid):
                continue
            row = stock_map.get(str(rid))
            if not row:
                continue
            d = float(row.get("district_stock") or 0.0)
            s = float(row.get("state_stock") or 0.0)
            n = float(row.get("national_stock") or 0.0)
            max_q = float(max_quantity_for(rid))
            # Need meaningful capacity in all tiers to hit all escalation variants.
            if d <= 1e-6 or s <= 1e-6 or n <= 1e-6:
                continue
            # If max allowed cannot exceed district+state, interstate/national cannot be reached.
            if max_q <= (d + s + 1.0):
                continue
            candidates.append((rid, d, s, n))

        targets = [
            "district_only",
            "district_state",
            "district_state_interstate",
            "district_state_interstate_national",
            "district_state_interstate_two",
        ]
        found: dict[str, CaseResult] = {}
        tried = []

        for rid, d, s, n in candidates:
            if len(found) == len(targets):
                break
            max_q = float(max_quantity_for(rid))
            quantities = propose_quantities(d, s, n)
            quantities += [
                float(int(max(1.0, math.floor(max_q * 0.75)))),
                float(int(max(1.0, math.floor(max_q * 0.90)))),
                float(int(max(1.0, math.floor(max_q * 0.98)))),
            ]
            dedup = []
            seen_q = set()
            for q in quantities:
                qn = float(int(q))
                if qn <= 0 or qn > max_q:
                    continue
                if qn in seen_q:
                    continue
                seen_q.add(qn)
                dedup.append(qn)
            quantities = dedup
            for qty in quantities:
                if len(found) == len(targets):
                    break
                try:
                    resp, summary = execute_request_and_optional_return(db, user, rid, qty)
                except ValueError as ve:
                    tried.append({
                        "resource_id": rid,
                        "quantity": qty,
                        "error": str(ve),
                    })
                    continue
                scopes = sorted(pattern_of(summary))
                tried.append({
                    "resource_id": rid,
                    "quantity": qty,
                    "request_id": summary["request_id"],
                    "solver_run_id": summary["solver_run_id"],
                    "request_status": summary["request_status"],
                    "run_status": summary["run_status"],
                    "scope_totals": summary["scope_totals"],
                    "neighbor_states": summary["neighbor_states"],
                    "neighbor_state_count": summary["neighbor_state_count"],
                    "unmet_total": summary["unmet_total"],
                    "scopes": scopes,
                })

                for t in targets:
                    if t in found:
                        continue
                    if matches_pattern(t, summary):
                        found[t] = CaseResult(
                            case_name=t,
                            resource_id=rid,
                            resource_name=str(CANONICAL_RESOURCE_NAME.get(rid, rid)),
                            quantity=float(qty),
                            request_id=int(summary["request_id"]),
                            solver_run_id=int(summary["solver_run_id"]),
                            request_status=str(summary["request_status"]),
                            scope_totals={k: float(v) for k, v in summary["scope_totals"].items()},
                            neighbor_states=list(summary["neighbor_states"]),
                            neighbor_state_count=int(summary["neighbor_state_count"]),
                            allocated_total=float(summary["allocated_total"]),
                            unmet_total=float(summary["unmet_total"]),
                            returned_total=float(summary.get("returned_total") or 0.0),
                        )
                        break

            # Keep run count in check.
            if len(tried) >= 60 and len(found) >= 3:
                break

        out = {
            "district_code": DISTRICT_CODE,
            "state_code": str(user["state_code"]),
            "time_slot": TIME_SLOT,
            "found_targets": {k: asdict(v) for k, v in found.items()},
            "targets": targets,
            "found_count": len(found),
            "tried_count": len(tried),
            "tried": tried[-120:],
        }

        out_path = "backend/DEMO_5_ESCALATION_TEST_CASES.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)

        print(json.dumps({
            "output_file": out_path,
            "found_count": len(found),
            "targets": targets,
            "found_targets": list(found.keys()),
            "district_code": DISTRICT_CODE,
            "state_code": str(user["state_code"]),
        }, indent=2))

    finally:
        db.close()


if __name__ == "__main__":
    main()
