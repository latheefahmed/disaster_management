import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import csv

from sqlalchemy import func

from app.database import SessionLocal
from app.models.allocation import Allocation
from app.models.district import District
from app.models.request import ResourceRequest
from app.models.scenario import Scenario
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.solver_run import SolverRun
from app.config import PHASE4_RESOURCE_DATA
from app.schemas.request import RequestCreate
from app.services.action_service import create_claim, create_return
from app.services.canonical_resources import CANONICAL_RESOURCE_NAME, max_quantity_for, requires_integer_quantity
from app.services.kpi_service import get_district_stock_rows, get_state_stock_rows
from app.services.request_service import create_request, get_district_requests_view
from app.services.resource_policy import is_resource_consumable, is_resource_returnable
from app.services.stock_refill_service import create_stock_refill

DISTRICT_CODE = "603"
MAX_WAIT_SEC = 240
EPSILON = 1e-6
MAX_ATTEMPTS_PER_CASE = 3
MAX_TOTAL_RUNS = 15


@dataclass
class AttemptResult:
    case_id: int
    case_name: str
    attempt_no: int
    resource_id: str
    resource_name: str
    quantity: float
    priority: int
    urgency: int
    time_index: int
    request_id: int
    solver_run_id: int
    run_status: str
    request_status: str
    allocated_quantity: float
    unmet_quantity: float
    district_alloc: float
    state_alloc: float
    interstate_alloc: float
    national_alloc: float
    interstate_state_count: int
    interstate_states: list[str]
    returned_quantity: float
    non_returnable_refilled_quantity: float
    utilization_district: float
    utilization_state: float
    utilization_interstate: float
    escalation_allowed_district: bool
    escalation_allowed_state: bool
    escalation_allowed_interstate: bool
    escalation_valid: bool
    escalation_violation_reason: str
    hierarchy_ok: bool
    percentage_match: bool
    percent_check: dict[str, Any]
    notes: str


def wait_run_completed(db, run_id: int, timeout_sec: int = MAX_WAIT_SEC) -> str:
    start = time.time()
    while time.time() - start < timeout_sec:
        db.expire_all()
        row = db.query(SolverRun).filter(SolverRun.id == int(run_id)).first()
        if row is None:
            return "missing"
        st = str(row.status or "").lower()
        if st in {"completed", "failed", "failed_reconciliation"}:
            return st
        time.sleep(1.0)
    return "timeout"


def _latest_scenario_id(db) -> int | None:
    row = db.query(Scenario.id).order_by(Scenario.id.desc()).first()
    return int(row[0]) if row else None


def build_resource_profiles(db, district_code: str, own_state_code: str) -> list[dict[str, Any]]:
    district_rows = get_district_stock_rows(db, district_code)
    district_map = {str(r["resource_id"]): dict(r) for r in district_rows}

    interstate_by_resource: dict[str, dict[str, float]] = {}

    # Prefer live stock API for interstate capacity because allocation gating uses live capacities.
    try:
        all_states = sorted({str(row.state_code) for row in db.query(District.state_code).all() if str(row.state_code or "").strip()})
        own = str(own_state_code)
        for sc in all_states:
            if str(sc) == own:
                continue
            try:
                rows = get_state_stock_rows(db, str(sc))
            except Exception:
                rows = []
            for row in rows:
                rid = str(row.get("resource_id") or "").strip()
                if not rid:
                    continue
                qty = float(row.get("state_stock") or 0.0)
                if qty <= EPSILON:
                    continue
                interstate_by_resource.setdefault(rid, {})[str(sc)] = float(qty)
    except Exception:
        interstate_by_resource = {}

    # Fallback: if scenario state stock is empty in DB, use static state stock CSV for interstate base.
    if not interstate_by_resource:
        state_csv = Path(PHASE4_RESOURCE_DATA) / "state_resource_stock.csv"
        own = str(own_state_code).lstrip("0") or "0"
        if state_csv.exists():
            with state_csv.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    rid = str(row.get("resource_id") or "").strip()
                    sc = str(row.get("state_code") or "").strip()
                    scn = sc.lstrip("0") or "0"
                    if not rid or not scn or scn == own:
                        continue
                    try:
                        qty = float(row.get("quantity") or 0.0)
                    except Exception:
                        qty = 0.0
                    if qty <= EPSILON:
                        continue
                    interstate_by_resource.setdefault(rid, {})[scn] = float(interstate_by_resource.get(rid, {}).get(scn, 0.0) + qty)

    profiles: list[dict[str, Any]] = []
    for rid, row in district_map.items():
        d_stock = float(row.get("district_stock") or 0.0)
        s_stock = float(row.get("state_stock") or 0.0)
        n_stock = float(row.get("national_stock") or 0.0)
        i_map = interstate_by_resource.get(rid, {})
        i_total = float(sum(v for v in i_map.values() if float(v) > EPSILON))
        i_count = len([1 for v in i_map.values() if float(v) > EPSILON])

        total_available = d_stock + s_stock + i_total + n_stock
        if total_available <= EPSILON:
            continue

        sorted_states = sorted(i_map.items(), key=lambda kv: float(kv[1]), reverse=True)
        top2_sum = float(sum(v for _, v in sorted_states[:2]))
        top5_sum = float(sum(v for _, v in sorted_states[:5]))

        profiles.append(
            {
                "resource_id": rid,
                "resource_name": str(CANONICAL_RESOURCE_NAME.get(rid, rid)),
                "district_stock": d_stock,
                "state_stock": s_stock,
                "interstate_stock": i_total,
                "interstate_state_count": i_count,
                "interstate_by_state": {k: float(v) for k, v in sorted_states},
                "national_stock": n_stock,
                "max_request_qty": float(max_quantity_for(rid)),
                "total_available": total_available,
                "district_capacity_ratio": d_stock / total_available,
                "state_capacity_ratio": s_stock / total_available,
                "interstate_capacity_ratio": i_total / total_available,
                "national_capacity_ratio": n_stock / total_available,
                "interstate_top2_sum": top2_sum,
                "interstate_top5_sum": top5_sum,
                "is_returnable": bool(is_resource_returnable(rid)),
                "is_consumable": bool(is_resource_consumable(rid)),
            }
        )

    profiles.sort(key=lambda x: (x["district_capacity_ratio"], x["total_available"]), reverse=True)
    return profiles


def summarize_allocations(db, request_id: int) -> dict[str, Any]:
    rows = db.query(Allocation).filter(Allocation.request_id == int(request_id)).all()
    d = s = i = n = 0.0
    unmet = 0.0
    interstate_states = set()
    time_groups: dict[tuple[int, str, str, str], float] = {}
    time_resource_alloc: dict[tuple[int, str], float] = {}

    for r in rows:
        qty = float(r.allocated_quantity or 0.0)
        if bool(r.is_unmet):
            unmet += qty
            continue

        scope = str(r.allocation_source_scope or r.supply_level or "district").strip().lower()
        if scope == "neighbor_state":
            scope = "interstate"
        if scope not in {"district", "state", "interstate", "national"}:
            scope = "district"

        if scope == "district":
            d += qty
        elif scope == "state":
            s += qty
        elif scope == "interstate":
            i += qty
            code = str(r.allocation_source_code or r.origin_state_code or r.state_code or "")
            if code and code.upper() != "NATIONAL":
                interstate_states.add(code)
        else:
            n += qty

        code = str(r.allocation_source_code or r.origin_state_code or r.state_code or "")
        t_idx = int(r.time or 0)
        slot_rid = str(r.resource_id or "")
        key = (t_idx, slot_rid, scope, code)
        time_groups[key] = float(time_groups.get(key, 0.0)) + qty
        time_resource_alloc[(t_idx, slot_rid)] = float(time_resource_alloc.get((t_idx, slot_rid), 0.0)) + qty

    alloc_total = d + s + i + n
    return {
        "district": d,
        "state": s,
        "interstate": i,
        "national": n,
        "allocated_total": alloc_total,
        "unmet_total": unmet,
        "interstate_states": sorted(interstate_states),
        "interstate_count": len(interstate_states),
        "time_groups": time_groups,
        "time_resource_alloc": time_resource_alloc,
    }


def _utilization(allocated: float, available: float) -> float:
    avail = max(0.0, float(available or 0.0))
    if avail <= EPSILON:
        return 1.0
    return max(0.0, float(allocated or 0.0)) / avail


def compute_escalation_tracking(requested: float, summary: dict[str, Any], stock: dict[str, Any]) -> dict[str, Any]:
    req = max(0.0, float(requested or 0.0))
    d_avail = max(0.0, float(stock.get("district_stock") or 0.0))
    s_avail = max(0.0, float(stock.get("state_stock") or 0.0))
    i_avail = max(0.0, float(stock.get("interstate_stock") or 0.0))

    d_alloc = max(0.0, float(summary.get("district") or 0.0))
    s_alloc = max(0.0, float(summary.get("state") or 0.0))
    i_alloc = max(0.0, float(summary.get("interstate") or 0.0))
    n_alloc = max(0.0, float(summary.get("national") or 0.0))

    score = int(stock.get("priority") or 0) + int(stock.get("urgency") or 0)
    t_idx = int(stock.get("time_index") or 0)

    allow_state = True
    if t_idx == 29:
        allow_interstate = False
        allow_national = False
    elif t_idx == 15:
        allow_interstate = score >= 8
        allow_national = False
    else:
        allow_interstate = score >= 8 and t_idx != 29
        allow_national = score >= 9 and t_idx == 0

    violations: list[str] = []
    if i_alloc > EPSILON and not allow_interstate:
        violations.append("interstate blocked by score/time rule")
    if n_alloc > EPSILON and not allow_national:
        violations.append("national blocked by score/time rule")
    if i_alloc > EPSILON and s_alloc <= EPSILON:
        violations.append("interstate used before state")
    if n_alloc > EPSILON and i_alloc <= EPSILON:
        violations.append("national used before interstate")
    if score <= 4 and (i_alloc > EPSILON or n_alloc > EPSILON):
        violations.append("local-only score should not escalate beyond state")

    return {
        "utilization_district": float(_utilization(d_alloc, d_avail)),
        "utilization_state": float(_utilization(s_alloc, s_avail)),
        "utilization_interstate": float(_utilization(i_alloc, i_avail)),
        "escalation_allowed_district": True,
        "escalation_allowed_state": True,
        "escalation_allowed_interstate": bool(allow_interstate),
        "escalation_valid": len(violations) == 0,
        "escalation_violation_reason": "; ".join(violations),
    }


def perform_reset(db, user: dict[str, str], run_id: int, summary: dict[str, Any]) -> dict[str, Any]:
    if float(summary["allocated_total"]) <= EPSILON:
        return {"mode": "none", "returned": 0.0, "refilled_non_returnable": 0.0, "notes": "nothing allocated"}

    returned = 0.0
    non_returnable_refilled = 0.0
    for (t_idx, slot_rid), slot_total in sorted(summary["time_resource_alloc"].items()):
        slot_total = float(slot_total)
        if slot_total <= EPSILON:
            continue

        grouped = [
            (scope, code, float(qty))
            for (gt, gr, scope, code), qty in summary["time_groups"].items()
            if int(gt) == int(t_idx) and str(gr) == str(slot_rid) and float(qty) > EPSILON
        ]

        if is_resource_consumable(slot_rid) or (not is_resource_returnable(slot_rid)):
            for scope, code, qty in grouped:
                if qty <= EPSILON:
                    continue
                if scope == "district":
                    create_stock_refill(
                        db=db,
                        scope="district",
                        resource_id=str(slot_rid),
                        quantity=float(qty),
                        actor_role="system",
                        actor_id="hierarchy_case_reset",
                        district_code=str(user["district_code"]),
                        state_code=str(user["state_code"]),
                        note="auto_refill_non_returnable",
                    )
                elif scope == "state":
                    create_stock_refill(
                        db=db,
                        scope="state",
                        resource_id=str(slot_rid),
                        quantity=float(qty),
                        actor_role="system",
                        actor_id="hierarchy_case_reset",
                        state_code=(str(code) if str(code).strip() else str(user["state_code"])),
                        note="auto_refill_non_returnable",
                    )
                elif scope == "interstate":
                    create_stock_refill(
                        db=db,
                        scope="state",
                        resource_id=str(slot_rid),
                        quantity=float(qty),
                        actor_role="system",
                        actor_id="hierarchy_case_reset",
                        state_code=(str(code) if str(code).strip() else str(user["state_code"])),
                        note="auto_refill_non_returnable",
                    )
                else:
                    create_stock_refill(
                        db=db,
                        scope="national",
                        resource_id=str(slot_rid),
                        quantity=float(qty),
                        actor_role="system",
                        actor_id="hierarchy_case_reset",
                        note="auto_refill_non_returnable",
                    )
                non_returnable_refilled += float(qty)
            continue

        integer_only = bool(requires_integer_quantity(str(slot_rid)))
        claim_qty = int(math.floor(slot_total + EPSILON)) if integer_only else float(slot_total)
        if float(claim_qty) <= EPSILON:
            continue

        create_claim(
            db=db,
            district_code=user["district_code"],
            resource_id=str(slot_rid),
            time=int(t_idx),
            quantity=float(claim_qty),
            claimed_by="district_manager",
            solver_run_id=int(run_id),
        )

        if integer_only:
            floors = []
            floor_sum = 0
            for scope, code, qty in grouped:
                base = int(math.floor(qty + 1e-9))
                frac = float(qty - base)
                floors.append((scope, code, base, frac))
                floor_sum += base
            remainder = max(0, int(claim_qty) - floor_sum)
            floors.sort(key=lambda x: x[3], reverse=True)
            adjusted = []
            for idx, (scope, code, base, _frac) in enumerate(floors):
                adjusted.append((scope, code, base + (1 if idx < remainder else 0)))
            emit = [(scope, code, float(q)) for scope, code, q in adjusted if int(q) > 0]
        else:
            emit = [(scope, code, qty) for scope, code, qty in grouped]

        for scope, code, qty in emit:
            source_scope = "neighbor_state" if scope == "interstate" else scope
            create_return(
                db=db,
                district_code=user["district_code"],
                state_code=user["state_code"],
                resource_id=str(slot_rid),
                time=int(t_idx),
                quantity=float(qty),
                reason="manual",
                solver_run_id=int(run_id),
                allocation_source_scope=source_scope,
                allocation_source_code=(code or None),
            )
            returned += float(qty)

    return {
        "mode": "return_and_refill",
        "returned": float(returned),
        "refilled_non_returnable": float(non_returnable_refilled),
        "notes": "returned returnable allocations and refilled non-returnables",
    }


def hierarchy_match(case_name: str, s: dict[str, Any]) -> bool:
    d = float(s["district"]) > EPSILON
    st = float(s["state"]) > EPSILON
    it = float(s["interstate"]) > EPSILON
    n = float(s["national"]) > EPSILON
    interstate_count = int(s["interstate_count"])

    if case_name == "district_only":
        return d and (not st) and (not it) and (not n) and float(s["unmet_total"]) <= EPSILON
    if case_name == "district_state":
        return d and st and (not it) and (not n)
    if case_name == "district_state_interstate":
        return d and st and it and (not n) and interstate_count <= 5
    if case_name == "full_escalation":
        return d and st and it and n and interstate_count <= 5
    if case_name == "district_state_interstate_two":
        return d and st and it and (not n) and interstate_count <= 2
    return False


def percentage_check(requested: float, s: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    req = max(float(requested), EPSILON)
    d_pct = 100.0 * float(s["district"]) / req
    st_pct = 100.0 * float(s["state"]) / req
    it_pct = 100.0 * float(s["interstate"]) / req
    n_pct = 100.0 * float(s["national"]) / req

    district_ok = 75.0 <= d_pct <= 95.0
    state_ok = st_pct <= 75.0
    interstate_ok = it_pct <= 60.0
    return (
        bool(district_ok and state_ok and interstate_ok),
        {
            "district_pct": d_pct,
            "state_pct": st_pct,
            "interstate_pct": it_pct,
            "national_pct": n_pct,
            "district_target_80_90_like": district_ok,
            "state_reasonable": state_ok,
            "interstate_reasonable": interstate_ok,
        },
    )


def status_from_totals(requested: float, allocated: float, unmet: float) -> str:
    req = float(requested)
    alloc = float(allocated)
    rem = max(0.0, req - alloc)
    if req <= EPSILON:
        return "allocated"
    if rem <= EPSILON or abs(unmet) <= EPSILON:
        return "allocated"
    if alloc <= EPSILON:
        return "failed"
    return "partial"


def clamp_qty(resource_id: str, qty: float) -> float:
    val = max(1.0, float(qty))
    val = min(val, float(max_quantity_for(resource_id)))
    if requires_integer_quantity(str(resource_id)):
        return float(max(1, int(round(val))))
    return float(val)


def select_case_candidates(profiles: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    eligible = [
        p for p in profiles
        if bool(p["is_returnable"]) and (not bool(p["is_consumable"])) and p["district_stock"] > 0.0
    ]

    district_only = sorted(
        [p for p in eligible if p["district_stock"] > 100.0],
        key=lambda p: p["district_capacity_ratio"],
        reverse=True,
    )

    district_state = sorted(
        [
            p for p in eligible
            if p["state_stock"] > 10.0
            and p["district_stock"] + 1.0 <= p["max_request_qty"]
        ],
        key=lambda p: ((p["max_request_qty"] - p["district_stock"]), p["state_stock"], -p["district_capacity_ratio"]),
        reverse=True,
    )

    with_interstate = sorted(
        [
            p for p in eligible
            if p["interstate_stock"] > 100.0
            and p["interstate_state_count"] > 0
            and (p["district_stock"] + p["state_stock"] + 1.0) <= p["max_request_qty"]
        ],
        key=lambda p: ((p["max_request_qty"] - (p["district_stock"] + p["state_stock"])), p["interstate_stock"]),
        reverse=True,
    )

    limited_interstate = sorted(
        [p for p in with_interstate if p["interstate_top2_sum"] > 0.0],
        key=lambda p: ((p["interstate_top2_sum"] / max(p["interstate_stock"], EPSILON)), (p["max_request_qty"] - (p["district_stock"] + p["state_stock"]))),
        reverse=True,
    )

    full = sorted(
        [
            p for p in with_interstate
            if p["national_stock"] > 100.0
            and (p["district_stock"] + p["state_stock"] + p["interstate_stock"] + 1.0) <= p["max_request_qty"]
        ],
        key=lambda p: p["national_stock"],
        reverse=True,
    )

    return {
        "district_only": district_only[:6],
        "district_state": district_state[:6],
        "district_state_interstate": with_interstate[:8],
        "full_escalation": full[:8],
        "district_state_interstate_two": limited_interstate[:8],
    }


def base_payload(case_name: str, profile: dict[str, Any]) -> dict[str, Any]:
    rid = str(profile["resource_id"])
    d = float(profile["district_stock"])
    s = float(profile["state_stock"])
    i_total = float(profile["interstate_stock"])
    n = float(profile["national_stock"])
    top2 = float(profile["interstate_top2_sum"])
    top5 = float(profile["interstate_top5_sum"])

    if case_name == "district_only":
        qty = max(1.0, d - 1.0)
        return {"resource_id": rid, "quantity": clamp_qty(rid, qty), "priority": 2, "urgency": 2, "time_index": 29}

    if case_name == "district_state":
        qty = d + max(1.0, min(1000.0, s))
        return {"resource_id": rid, "quantity": clamp_qty(rid, qty), "priority": 3, "urgency": 3, "time_index": 15}

    if case_name == "district_state_interstate":
        qty = d + s + max(1.0, min(5000.0, i_total))
        return {"resource_id": rid, "quantity": clamp_qty(rid, qty), "priority": 5, "urgency": 5, "time_index": 0}

    if case_name == "district_state_interstate_two":
        qty = d + s + max(1.0, min(4000.0, top2))
        return {"resource_id": rid, "quantity": clamp_qty(rid, qty), "priority": 5, "urgency": 4, "time_index": 0}

    if case_name == "full_escalation":
        near_max = max(d + s + i_total + 1.0, d + s + i_total + max(1.0, min(20000.0, n)))
        qty = min(float(profile["max_request_qty"]), near_max)
        return {"resource_id": rid, "quantity": clamp_qty(rid, qty), "priority": 5, "urgency": 5, "time_index": 0}

    qty = d + 1.0
    return {"resource_id": rid, "quantity": clamp_qty(rid, qty), "priority": 3, "urgency": 3, "time_index": 15}


def adjust_payload(case_name: str, payload: dict[str, Any], summary: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    qty = float(payload["quantity"])
    d = float(profile["district_stock"])
    s = float(profile["state_stock"])
    i_total = float(profile["interstate_stock"])
    top2 = float(profile["interstate_top2_sum"])

    has_state = float(summary["state"]) > EPSILON
    has_inter = float(summary["interstate"]) > EPSILON
    has_national = float(summary["national"]) > EPSILON
    inter_states = int(summary["interstate_count"])

    if case_name == "district_only":
        if has_state or has_inter or has_national:
            qty = max(1.0, d - 1.0)

    elif case_name == "district_state":
        if not has_state:
            qty = qty + max(1.0, min(1000.0, s))
        if has_inter or has_national:
            qty = max(d + 1.0, qty - max(1.0, min(1000.0, i_total + 1.0)))

    elif case_name == "district_state_interstate":
        if not has_inter:
            qty = qty + max(1.0, min(3000.0, i_total))
        if has_national:
            qty = max(d + s + 1.0, qty - max(1.0, min(3000.0, top2 + 1.0)))

    elif case_name == "district_state_interstate_two":
        lower = d + s + 1.0
        upper = d + s + max(1.0, min(top2, i_total))
        if not has_inter:
            qty = qty + max(1.0, min(1500.0, top2))
        elif inter_states > 2 or has_national:
            qty = max(lower, qty - max(1.0, min(1500.0, top2)))
        qty = min(qty, upper)

    elif case_name == "full_escalation":
        if not has_national:
            qty = qty + max(1.0, min(5000.0, float(profile.get("national_stock") or 0.0)))
        else:
            qty = max(qty, d + s + i_total + 1.0)

    payload["quantity"] = clamp_qty(str(payload["resource_id"]), qty)
    return payload


def run_attempt(db, user: dict[str, str], case_id: int, case_name: str, attempt_no: int, payload: dict[str, Any], profile: dict[str, Any]) -> AttemptResult:
    rid = str(payload["resource_id"])
    req = RequestCreate(
        resource_id=rid,
        time=int(payload["time_index"]),
        quantity=float(payload["quantity"]),
        priority=int(payload["priority"]),
        urgency=int(payload["urgency"]),
        confidence=1.0,
        source="human",
    )

    created = create_request(db, user, req)
    request_id = int(created["request_id"])
    run_id = int(created["solver_run_id"])

    run_status = wait_run_completed(db, run_id)
    _ = get_district_requests_view(db, user["district_code"], latest_only=False, limit=10, offset=0)

    row = db.query(ResourceRequest).filter(ResourceRequest.id == request_id).first()
    summary = summarize_allocations(db, request_id)
    stock_snapshot = {
        "district_stock": float(profile.get("district_stock") or 0.0),
        "state_stock": float(profile.get("state_stock") or 0.0),
        "interstate_stock": float(profile.get("interstate_stock") or 0.0),
        "national_stock": float(profile.get("national_stock") or 0.0),
        "priority": int(payload.get("priority") or 0),
        "urgency": int(payload.get("urgency") or 0),
        "time_index": int(payload.get("time_index") or 0),
    }
    escalation_tracking = compute_escalation_tracking(float(payload["quantity"]), summary, stock_snapshot)
    reset_result = perform_reset(db, user, run_id, summary)

    expected_status = status_from_totals(float(payload["quantity"]), float(summary["allocated_total"]), float(summary["unmet_total"]))
    hierarchy_ok = hierarchy_match(case_name, summary)
    pct_ok, pct_detail = percentage_check(float(payload["quantity"]), summary)

    notes = []
    if not hierarchy_ok:
        notes.append("hierarchy mismatch")
    if int(summary["interstate_count"]) > 5:
        notes.append("interstate states exceeded 5")
    if str(expected_status) != str((row.status if row else "missing")):
        notes.append(f"status_expected={expected_status}")
    notes.append(f"reset_mode={reset_result['mode']}")

    return AttemptResult(
        case_id=case_id,
        case_name=case_name,
        attempt_no=attempt_no,
        resource_id=rid,
        resource_name=str(CANONICAL_RESOURCE_NAME.get(rid, rid)),
        quantity=float(payload["quantity"]),
        priority=int(payload["priority"]),
        urgency=int(payload["urgency"]),
        time_index=int(payload["time_index"]),
        request_id=request_id,
        solver_run_id=run_id,
        run_status=str(run_status),
        request_status=str(row.status if row else "missing"),
        allocated_quantity=float(summary["allocated_total"]),
        unmet_quantity=float(summary["unmet_total"]),
        district_alloc=float(summary["district"]),
        state_alloc=float(summary["state"]),
        interstate_alloc=float(summary["interstate"]),
        national_alloc=float(summary["national"]),
        interstate_state_count=int(summary["interstate_count"]),
        interstate_states=list(summary["interstate_states"]),
        returned_quantity=float(reset_result.get("returned", 0.0)),
        non_returnable_refilled_quantity=float(reset_result.get("refilled_non_returnable", 0.0)),
        utilization_district=float(escalation_tracking["utilization_district"]),
        utilization_state=float(escalation_tracking["utilization_state"]),
        utilization_interstate=float(escalation_tracking["utilization_interstate"]),
        escalation_allowed_district=bool(escalation_tracking["escalation_allowed_district"]),
        escalation_allowed_state=bool(escalation_tracking["escalation_allowed_state"]),
        escalation_allowed_interstate=bool(escalation_tracking["escalation_allowed_interstate"]),
        escalation_valid=bool(escalation_tracking["escalation_valid"]),
        escalation_violation_reason=str(escalation_tracking["escalation_violation_reason"]),
        hierarchy_ok=bool(hierarchy_ok),
        percentage_match=bool(pct_ok),
        percent_check=dict(pct_detail),
        notes="; ".join(notes) if notes else "ok",
    )


def run_case(db, user: dict[str, str], case_id: int, case_name: str, candidates: list[dict[str, Any]], max_runs: int) -> tuple[AttemptResult | None, list[dict[str, Any]], int]:
    logs: list[dict[str, Any]] = []
    if not candidates:
        return None, logs, 0

    selected = None
    escalation_heavy = case_name in {"full_escalation", "district_state_interstate", "district_state_interstate_two"}
    max_candidates = int(max_runs) if escalation_heavy else 2
    attempts_per_profile = 1 if escalation_heavy else MAX_ATTEMPTS_PER_CASE
    attempt_no = 0

    for profile in candidates[:max_candidates]:
        payload = base_payload(case_name, profile)
        for _ in range(attempts_per_profile):
            if attempt_no >= int(max_runs):
                if selected is None and logs:
                    selected = AttemptResult(**logs[-1])
                return selected, logs, attempt_no
            attempt_no += 1
            result = run_attempt(db, user, case_id, case_name, attempt_no, dict(payload), profile)
            logs.append(asdict(result))

            if selected is None:
                selected = result
            else:
                if result.hierarchy_ok and (not selected.hierarchy_ok):
                    selected = result
                elif result.hierarchy_ok == selected.hierarchy_ok and result.escalation_valid and (not selected.escalation_valid):
                    selected = result

            if result.hierarchy_ok:
                return result, logs, attempt_no

            if not escalation_heavy:
                payload = adjust_payload(case_name, payload, {
                    "district": result.district_alloc,
                    "state": result.state_alloc,
                    "interstate": result.interstate_alloc,
                    "national": result.national_alloc,
                    "interstate_count": result.interstate_state_count,
                }, profile)

    if selected is None and logs:
        selected = AttemptResult(**logs[-1])

    return selected, logs, attempt_no


def main() -> None:
    db = SessionLocal()
    try:
        district = db.query(District).filter(District.district_code == DISTRICT_CODE).first()
        if district is None:
            raise RuntimeError("District 603 not found")

        user = {
            "district_code": str(district.district_code),
            "state_code": str(district.state_code),
            "role": "district",
        }

        profiles = build_resource_profiles(db, DISTRICT_CODE, user["state_code"])
        candidate_sets = select_case_candidates(profiles)

        case_plan = [
            (1, "district_only"),
            (2, "district_state"),
            (3, "district_state_interstate"),
            (4, "district_state_interstate_two"),
            (5, "full_escalation"),
        ]
        case_run_budget = {
            "district_only": 1,
            "district_state": 1,
            "district_state_interstate": 4,
            "district_state_interstate_two": 4,
            "full_escalation": 5,
        }

        attempts_log: list[dict[str, Any]] = []
        final_cases: list[dict[str, Any]] = []

        runs_remaining = int(MAX_TOTAL_RUNS)
        case3_resource_id: str | None = None
        for case_id, case_name in case_plan:
            candidates = list(candidate_sets.get(case_name, []))
            if case_name == "district_state_interstate_two" and case3_resource_id:
                preferred = [c for c in candidates if str(c.get("resource_id")) == str(case3_resource_id)]
                if preferred:
                    others = [c for c in candidates if str(c.get("resource_id")) != str(case3_resource_id)]
                    candidates = preferred + others

            run_cap = min(runs_remaining, int(case_run_budget.get(case_name, MAX_ATTEMPTS_PER_CASE)))
            selected, logs, used = run_case(db, user, case_id, case_name, candidates, run_cap)
            runs_remaining = max(0, runs_remaining - int(used))
            attempts_log.extend(logs)
            if selected is not None:
                selected_row = asdict(selected)
                selected_profile = next((p for p in profiles if str(p["resource_id"]) == str(selected_row["resource_id"])), None)
                selected_row["stock_snapshot_used"] = {
                    "district_stock": float((selected_profile or {}).get("district_stock", 0.0)),
                    "state_stock": float((selected_profile or {}).get("state_stock", 0.0)),
                    "interstate_stock": float((selected_profile or {}).get("interstate_stock", 0.0)),
                    "national_stock": float((selected_profile or {}).get("national_stock", 0.0)),
                }
                selected_row["capacity_ratios"] = {
                    "district_capacity_ratio": float((selected_profile or {}).get("district_capacity_ratio", 0.0)),
                    "state_capacity_ratio": float((selected_profile or {}).get("state_capacity_ratio", 0.0)),
                    "interstate_capacity_ratio": float((selected_profile or {}).get("interstate_capacity_ratio", 0.0)),
                    "national_capacity_ratio": float((selected_profile or {}).get("national_capacity_ratio", 0.0)),
                }
                final_cases.append(selected_row)
                if case_name == "district_state_interstate":
                    case3_resource_id = str(selected_row.get("resource_id"))
            if runs_remaining <= 0:
                break

        out = {
            "district_code": DISTRICT_CODE,
            "state_code": str(user["state_code"]),
            "execution_mode": "deterministic_score_time_control_fast",
            "epsilon": EPSILON,
            "max_attempts_per_case": MAX_ATTEMPTS_PER_CASE,
            "max_total_runs": MAX_TOTAL_RUNS,
            "resource_stock_analysis": profiles,
            "attempts_total": len(attempts_log),
            "attempts_log": attempts_log,
            "final_case_count": len(final_cases),
            "final_cases": final_cases,
            "all_cases_hierarchy_ok": all(bool(c.get("hierarchy_ok")) for c in final_cases) and len(final_cases) == 5,
            "district_state_interstate_two_ok": any(c.get("case_name") == "district_state_interstate_two" and int(c.get("interstate_state_count", 0)) <= 2 and float(c.get("national_alloc", 0.0)) <= EPSILON for c in final_cases),
            "all_ready_for_demo": all(bool(c.get("hierarchy_ok")) and bool(c.get("escalation_valid")) for c in final_cases) and len(final_cases) == 5,
        }

        out_path = "HIERARCHY_5_TEST_CASES_REPORT.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)

        print(json.dumps({
            "out_path": out_path,
            "attempts_total": len(attempts_log),
            "final_case_count": len(final_cases),
            "all_cases_hierarchy_ok": out["all_cases_hierarchy_ok"],
            "district_state_interstate_two_ok": out["district_state_interstate_two_ok"],
            "all_ready_for_demo": out["all_ready_for_demo"],
            "final_cases": [
                {
                    "case_id": c["case_id"],
                    "case_name": c["case_name"],
                    "resource_id": c["resource_id"],
                    "quantity": c["quantity"],
                    "status": c["request_status"],
                    "hierarchy_ok": c["hierarchy_ok"],
                    "interstate_state_count": c["interstate_state_count"],
                    "breakdown": {
                        "district": c["district_alloc"],
                        "state": c["state_alloc"],
                        "interstate": c["interstate_alloc"],
                        "national": c["national_alloc"],
                        "unmet": c["unmet_quantity"],
                    },
                }
                for c in final_cases
            ],
        }, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
