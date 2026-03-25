import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.models.district import District
from app.models.request import ResourceRequest
from app.schemas.request import RequestCreate
from app.services.canonical_resources import CANONICAL_RESOURCE_NAME
from app.services.request_service import create_request, get_district_requests_view

from scripts.generate_5_hierarchy_cases import (
    DISTRICT_CODE,
    EPSILON,
    SessionLocal,
    clamp_qty,
    hierarchy_match,
    status_from_totals,
    summarize_allocations,
    wait_run_completed,
)

MAX_RETRIES_PER_CASE = 2
REPORT_PATH = Path("HIERARCHY_5_TEST_CASES_REPORT.json")
OUT_PATH = Path("HIERARCHY_5_TEST_CASES_REPORT_REFINED.json")
UTILIZATION_GATE_RATIO = 0.80


@dataclass
class RefinedAttempt:
    case_id: int
    case_name: str
    attempt_no: int
    resource_id: str
    quantity: float
    priority: int
    urgency: int
    time_index: int
    request_id: int
    solver_run_id: int
    run_status: str
    request_status: str
    expected_status: str
    status_correct: bool
    hierarchy_ok: bool
    allocated_quantity: float
    unmet_quantity: float
    district_alloc: float
    state_alloc: float
    interstate_alloc: float
    national_alloc: float
    interstate_state_count: int
    interstate_states: list[str]
    district_pct: float
    state_pct: float
    interstate_pct: float
    national_pct: float
    utilization_district: float
    utilization_state: float
    utilization_interstate: float
    escalation_allowed_district: bool
    escalation_allowed_state: bool
    escalation_allowed_interstate: bool
    escalation_valid: bool
    escalation_violation_reason: str
    percentage_distance: float
    notes: str


def _load_existing_cases() -> list[dict[str, Any]]:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    rows = payload.get("final_cases") or []
    if len(rows) != 5:
        raise RuntimeError("Expected 5 final cases in source report")
    return rows


def _pct_metrics(quantity: float, summary: dict[str, Any]) -> dict[str, float]:
    req = max(float(quantity), EPSILON)
    return {
        "district": 100.0 * float(summary["district"]) / req,
        "state": 100.0 * float(summary["state"]) / req,
        "interstate": 100.0 * float(summary["interstate"]) / req,
        "national": 100.0 * float(summary["national"]) / req,
    }


def _utilization(allocated: float, available: float) -> float:
    avail = max(0.0, float(available or 0.0))
    if avail <= EPSILON:
        return 1.0
    return max(0.0, float(allocated or 0.0)) / avail


def _escalation_tracking(quantity: float, summary: dict[str, Any], stock_snapshot: dict[str, Any]) -> dict[str, Any]:
    req = max(0.0, float(quantity or 0.0))
    d_avail = max(0.0, float(stock_snapshot.get("district_stock") or 0.0))
    s_avail = max(0.0, float(stock_snapshot.get("state_stock") or 0.0))
    i_avail = max(0.0, float(stock_snapshot.get("interstate_stock") or 0.0))

    d_alloc = max(0.0, float(summary.get("district") or 0.0))
    s_alloc = max(0.0, float(summary.get("state") or 0.0))
    i_alloc = max(0.0, float(summary.get("interstate") or 0.0))
    n_alloc = max(0.0, float(summary.get("national") or 0.0))

    rem_after_d = max(0.0, req - d_alloc)
    rem_after_s = max(0.0, req - d_alloc - s_alloc)
    rem_after_i = max(0.0, req - d_alloc - s_alloc - i_alloc)

    d_ok = (rem_after_d <= EPSILON) or (d_avail <= EPSILON) or (d_alloc + EPSILON >= UTILIZATION_GATE_RATIO * d_avail) or (d_alloc + EPSILON >= d_avail)
    s_ok = (rem_after_s <= EPSILON) or (s_avail <= EPSILON) or (s_alloc + EPSILON >= UTILIZATION_GATE_RATIO * s_avail) or (s_alloc + EPSILON >= s_avail)
    i_ok = (rem_after_i <= EPSILON) or (i_avail <= EPSILON) or (i_alloc + EPSILON >= UTILIZATION_GATE_RATIO * i_avail) or (i_alloc + EPSILON >= i_avail)

    violations: list[str] = []
    if s_alloc > EPSILON and not d_ok:
        violations.append("utilization below 80% threshold at district")
    if i_alloc > EPSILON and not s_ok:
        violations.append("utilization below 80% threshold at state")
    if n_alloc > EPSILON and not i_ok:
        violations.append("utilization below 80% threshold at interstate")

    return {
        "utilization_district": float(_utilization(d_alloc, d_avail)),
        "utilization_state": float(_utilization(s_alloc, s_avail)),
        "utilization_interstate": float(_utilization(i_alloc, i_avail)),
        "escalation_allowed_district": bool(d_ok),
        "escalation_allowed_state": bool(s_ok),
        "escalation_allowed_interstate": bool(i_ok),
        "escalation_valid": len(violations) == 0,
        "escalation_violation_reason": "; ".join(violations),
    }


def _percentage_distance(case_name: str, pct: dict[str, float]) -> float:
    d = float(pct["district"])
    s = float(pct["state"])
    i = float(pct["interstate"])

    d_penalty = abs(d - 85.0)

    if case_name == "district_only":
        return abs(d - 95.0)

    remaining = max(0.0, 100.0 - d)
    state_target = 0.60 * remaining
    interstate_target = 0.30 * remaining

    if case_name == "district_state":
        return d_penalty + abs(s - remaining) + (i * 2.0)

    return d_penalty + abs(s - state_target) + abs(i - interstate_target)


def _adjust_payload(case_name: str, payload: dict[str, Any], pct: dict[str, float], summary: dict[str, Any], retry_no: int, escalation_valid: bool) -> dict[str, Any]:
    qty = float(payload["quantity"])
    d_pct = float(pct["district"])
    i_pct = float(pct["interstate"])

    step = 0.10 if retry_no == 1 else 0.07

    if d_pct < 80.0:
        qty *= (1.0 - step)
    elif d_pct > 90.0:
        qty *= (1.0 + step)

    if case_name == "district_state":
        if float(summary["state"]) <= EPSILON:
            qty *= 1.12
        if i_pct > EPSILON:
            qty *= 0.90

    if case_name in {"district_state_interstate", "limited_interstate", "full_escalation"}:
        if float(summary["interstate"]) <= EPSILON:
            qty *= 1.12
        elif i_pct > 45.0:
            qty *= 0.90

    if case_name == "full_escalation":
        threshold = float(summary.get("district", 0.0)) + float(summary.get("state", 0.0)) + float(summary.get("interstate", 0.0))
        unmet = max(0.0, float(payload.get("quantity", 0.0)) - (float(summary.get("allocated_total", 0.0))))

        # If unmet appears, snap toward the just-above-threshold band so national is used without forcing partial.
        if unmet > EPSILON and threshold > EPSILON:
            qty = threshold + 250.0
        elif float(summary["national"]) <= EPSILON:
            qty = max(qty * 1.12, threshold + 250.0)

    if case_name == "limited_interstate" and int(summary.get("interstate_count", 0)) > 2:
        qty *= 0.88

    if not escalation_valid:
        qty *= 1.18

    payload["quantity"] = float(clamp_qty(str(payload["resource_id"]), qty))

    if retry_no == 2:
        payload["time_index"] = 0 if int(payload.get("time_index", 10)) != 0 else 10

    return payload


def _cleanup_run_artifacts(run_id: int, request_id: int) -> None:
    conn = sqlite3.connect("backend.db")
    cur = conn.cursor()

    for table, col in [
        ("claims", "solver_run_id"),
        ("returns", "solver_run_id"),
        ("allocations", "solver_run_id"),
        ("inventory_snapshots", "solver_run_id"),
        ("shipment_plans", "solver_run_id"),
        ("final_demands", "solver_run_id"),
        ("stock_refill_transactions", "solver_run_id"),
    ]:
        cur.execute(f"DELETE FROM {table} WHERE {col} = ?", (int(run_id),))

    cur.execute("DELETE FROM requests WHERE id = ?", (int(request_id),))
    cur.execute("DELETE FROM requests WHERE run_id = ?", (int(run_id),))
    cur.execute("DELETE FROM solver_runs WHERE id = ?", (int(run_id),))

    conn.commit()
    conn.close()


def _run_once(db, user: dict[str, str], case: dict[str, Any], attempt_no: int, payload: dict[str, Any]) -> RefinedAttempt:
    req = RequestCreate(
        resource_id=str(payload["resource_id"]),
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
    pct = _pct_metrics(float(payload["quantity"]), summary)
    stock_snapshot = dict((case.get("stock_snapshot_used") or {}))
    escalation = _escalation_tracking(float(payload["quantity"]), summary, stock_snapshot)

    expected_status = status_from_totals(float(payload["quantity"]), float(summary["allocated_total"]), float(summary["unmet_total"]))
    actual_status = str(row.status if row else "missing")
    status_correct = actual_status == expected_status

    notes = []
    if not hierarchy_match(str(case["case_name"]), summary):
        notes.append("hierarchy_mismatch")
    if not status_correct:
        notes.append(f"status_expected={expected_status}")
    if not bool(escalation["escalation_valid"]):
        notes.append(str(escalation["escalation_violation_reason"]))

    result = RefinedAttempt(
        case_id=int(case["case_id"]),
        case_name=str(case["case_name"]),
        attempt_no=int(attempt_no),
        resource_id=str(payload["resource_id"]),
        quantity=float(payload["quantity"]),
        priority=int(payload["priority"]),
        urgency=int(payload["urgency"]),
        time_index=int(payload["time_index"]),
        request_id=request_id,
        solver_run_id=run_id,
        run_status=str(run_status),
        request_status=actual_status,
        expected_status=str(expected_status),
        status_correct=bool(status_correct),
        hierarchy_ok=bool(hierarchy_match(str(case["case_name"]), summary)),
        allocated_quantity=float(summary["allocated_total"]),
        unmet_quantity=float(summary["unmet_total"]),
        district_alloc=float(summary["district"]),
        state_alloc=float(summary["state"]),
        interstate_alloc=float(summary["interstate"]),
        national_alloc=float(summary["national"]),
        interstate_state_count=int(summary["interstate_count"]),
        interstate_states=list(summary["interstate_states"]),
        district_pct=float(pct["district"]),
        state_pct=float(pct["state"]),
        interstate_pct=float(pct["interstate"]),
        national_pct=float(pct["national"]),
        utilization_district=float(escalation["utilization_district"]),
        utilization_state=float(escalation["utilization_state"]),
        utilization_interstate=float(escalation["utilization_interstate"]),
        escalation_allowed_district=bool(escalation["escalation_allowed_district"]),
        escalation_allowed_state=bool(escalation["escalation_allowed_state"]),
        escalation_allowed_interstate=bool(escalation["escalation_allowed_interstate"]),
        escalation_valid=bool(escalation["escalation_valid"]),
        escalation_violation_reason=str(escalation["escalation_violation_reason"]),
        percentage_distance=float(_percentage_distance(str(case["case_name"]), pct)),
        notes=";".join(notes) if notes else "ok",
    )

    _cleanup_run_artifacts(run_id, request_id)
    return result


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

        source_cases = _load_existing_cases()
        attempts_log: list[dict[str, Any]] = []
        final_cases: list[dict[str, Any]] = []

        for case in source_cases:
            payload = {
                "resource_id": str(case["resource_id"]),
                "quantity": float(case["quantity"]),
                "priority": int(case["priority"]),
                "urgency": int(case["urgency"]),
                "time_index": int(case["time_index"]),
            }

            best: RefinedAttempt | None = None

            for attempt_no in range(1, MAX_RETRIES_PER_CASE + 2):
                run = _run_once(db, user, case, attempt_no, dict(payload))
                attempts_log.append(asdict(run))

                if best is None:
                    best = run
                else:
                    if run.hierarchy_ok and (not best.hierarchy_ok):
                        best = run
                    elif run.hierarchy_ok == best.hierarchy_ok:
                        if run.escalation_valid and (not best.escalation_valid):
                            best = run
                        elif run.escalation_valid == best.escalation_valid and run.status_correct and (not best.status_correct):
                            best = run
                        elif run.escalation_valid == best.escalation_valid and run.status_correct == best.status_correct and run.percentage_distance < best.percentage_distance:
                            best = run

                if attempt_no <= MAX_RETRIES_PER_CASE:
                    pct = {
                        "district": run.district_pct,
                        "state": run.state_pct,
                        "interstate": run.interstate_pct,
                    }
                    summ = {
                        "district": run.district_alloc,
                        "state": run.state_alloc,
                        "interstate": run.interstate_alloc,
                        "national": run.national_alloc,
                        "interstate_count": run.interstate_state_count,
                    }
                    payload = _adjust_payload(str(case["case_name"]), dict(payload), pct, summ, attempt_no, bool(run.escalation_valid))

            if best is None:
                continue

            row = asdict(best)
            row["resource_name"] = str(CANONICAL_RESOURCE_NAME.get(best.resource_id, best.resource_id))
            row["ready_for_demo"] = bool(best.hierarchy_ok and best.status_correct)
            final_cases.append(row)

        out = {
            "district_code": DISTRICT_CODE,
            "execution_mode": "non_mutating_refine_existing_cases_max2_retries",
            "epsilon": EPSILON,
            "max_retries_per_case": MAX_RETRIES_PER_CASE,
            "source_report": str(REPORT_PATH),
            "attempts_total": len(attempts_log),
            "attempts_log": attempts_log,
            "final_case_count": len(final_cases),
            "final_cases": final_cases,
            "all_hierarchy_ok": all(bool(c.get("hierarchy_ok")) for c in final_cases) and len(final_cases) == 5,
            "all_status_consistent": all(bool(c.get("status_correct")) for c in final_cases) and len(final_cases) == 5,
            "all_escalation_valid": all(bool(c.get("escalation_valid")) for c in final_cases) and len(final_cases) == 5,
        }

        OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")

        print(json.dumps(
            {
                "out_path": str(OUT_PATH),
                "final_case_count": len(final_cases),
                "all_hierarchy_ok": out["all_hierarchy_ok"],
                "all_status_consistent": out["all_status_consistent"],
                "final_cases": [
                    {
                        "case_id": c["case_id"],
                        "case_name": c["case_name"],
                        "resource_id": c["resource_id"],
                        "quantity": c["quantity"],
                        "status": c["request_status"],
                        "expected_status": c["expected_status"],
                        "status_correct": c["status_correct"],
                        "hierarchy_ok": c["hierarchy_ok"],
                        "percentages": {
                            "district": c["district_pct"],
                            "state": c["state_pct"],
                            "interstate": c["interstate_pct"],
                        },
                        "ready_for_demo": c["ready_for_demo"],
                    }
                    for c in final_cases
                ],
            },
            indent=2,
        ))
    finally:
        db.close()


if __name__ == "__main__":
    main()
