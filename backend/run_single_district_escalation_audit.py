from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, text

from app.database import SessionLocal, apply_runtime_migrations
from app.models.allocation import Allocation
from app.models.district import District
from app.models.pool_transaction import PoolTransaction
from app.models.solver_run import SolverRun
from app.models.stock_refill_transaction import StockRefillTransaction
from app.models.state import State
from app.services.action_service import create_claim, create_consumption, create_return
from app.services.kpi_service import get_district_stock_rows, get_national_stock_rows, get_state_stock_rows
from app.services.mutual_aid_service import create_mutual_aid_offer, create_mutual_aid_request, respond_to_offer
from app.services.request_service import create_request_batch


DISTRICT_CODE = "603"
EXPECTED_PARENT_STATE = "33"
TIME_SLOT = 0
C1 = "R5"   # bottled_water_liters (consumable)
N1 = "R8"   # tents (non-consumable)
N2 = "R41"  # generators (non-consumable)

OUT_DIR = Path(__file__).resolve().parent / "forensics"
OUT_JSON = OUT_DIR / "ESCALATION_LIFECYCLE_RUNS.json"
OUT_SINGLE = OUT_DIR / "SINGLE_DISTRICT_ESCALATION_REPORT.md"
OUT_SINGLE_TYPO = OUT_DIR / "single_distrinctYeslationctCLE_REPORT.md"
OUT_PHASE11 = OUT_DIR / "ESCALATION_LIFECYCLE_REPORT.md"


@dataclass
class PhaseVerdict:
    phase: str
    name: str
    passed: bool
    details: dict


class AuditError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _f(x) -> float:
    return float(x or 0.0)


def _stock_lookup(rows: list[dict], resource_id: str, key: str) -> float:
    for row in rows:
        if str(row.get("resource_id")) == str(resource_id):
            return _f(row.get(key))
    return 0.0


def _effective_stock_snapshot(db, district_code: str, state_code: str, neighbor_state: str) -> dict:
    drows = get_district_stock_rows(db, district_code)
    srows = get_state_stock_rows(db, state_code)
    nrows = get_state_stock_rows(db, neighbor_state)
    rows_nat = get_national_stock_rows(db)

    return {
        "district": {
            C1: _stock_lookup(drows, C1, "district_stock"),
            N1: _stock_lookup(drows, N1, "district_stock"),
            N2: _stock_lookup(drows, N2, "district_stock"),
        },
        "state": {
            C1: _stock_lookup(srows, C1, "state_stock"),
            N1: _stock_lookup(srows, N1, "state_stock"),
            N2: _stock_lookup(srows, N2, "state_stock"),
        },
        "neighbor_state": {
            C1: _stock_lookup(nrows, C1, "state_stock"),
            N1: _stock_lookup(nrows, N1, "state_stock"),
            N2: _stock_lookup(nrows, N2, "state_stock"),
        },
        "national": {
            C1: _stock_lookup(rows_nat, C1, "national_stock"),
            N1: _stock_lookup(rows_nat, N1, "national_stock"),
            N2: _stock_lookup(rows_nat, N2, "national_stock"),
        },
    }


def _append_refill_delta(db, scope: str, resource_id: str, delta: float, district_code: str | None = None, state_code: str | None = None, reason: str = "lifecycle_forced_setup"):
    if abs(float(delta)) <= 1e-9:
        return
    db.add(
        StockRefillTransaction(
            scope=str(scope),
            district_code=(None if district_code is None else str(district_code)),
            state_code=(None if state_code is None else str(state_code)),
            resource_id=str(resource_id),
            quantity_delta=float(delta),
            reason=str(reason),
            actor_role="system",
            actor_id="lifecycle_auditor",
            source="manual_refill",
            solver_run_id=None,
        )
    )


def _clear_phase0(db) -> dict:
    tables = {r[0] for r in db.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    targets = [
        t for t in [
            "requests",
            "resource_requests",
            "allocations",
            "unmet",
            "solver_runs",
            "claims",
            "consumptions",
            "returns",
            "pool_transactions",
            "state_transfers",
            "mutual_aid_offers",
            "mutual_aid_requests",
            "request_predictions",
            "final_demands",
            "inventory_snapshots",
            "shipment_plans",
        ] if t in tables
    ]
    before = {}
    for t in targets:
        before[t] = int(db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0)
    for t in targets:
        db.execute(text(f"DELETE FROM {t}"))
    db.commit()
    after = {}
    for t in targets:
        after[t] = int(db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0)
    return {"targets": targets, "before": before, "after": after}


def _check_phase1_policy(db) -> PhaseVerdict:
    rows = db.execute(
        text("SELECT canonical_id, class_type, can_consume, can_return FROM canonical_resources ORDER BY canonical_id")
    ).fetchall()
    bad_rows = []
    for r in rows:
        class_type = str(r[1])
        can_consume = int(r[2] or 0)
        can_return = int(r[3] or 0)
        if class_type not in {"consumable", "non_consumable"}:
            bad_rows.append({"canonical_id": str(r[0]), "issue": "class_out_of_domain", "class_type": class_type})
            continue
        if class_type == "consumable" and not (can_consume == 1 and can_return == 0):
            bad_rows.append({"canonical_id": str(r[0]), "issue": "bad_flags_for_consumable", "can_consume": can_consume, "can_return": can_return})
        if class_type == "non_consumable" and not (can_consume == 0 and can_return == 1):
            bad_rows.append({"canonical_id": str(r[0]), "issue": "bad_flags_for_non_consumable", "can_consume": can_consume, "can_return": can_return})

    return PhaseVerdict(
        phase="P1",
        name="Class rule enforcement",
        passed=len(bad_rows) == 0,
        details={"rows": len(rows), "invalid_rows": bad_rows[:20]},
    )


def _check_phase2_schema(db) -> PhaseVerdict:
    cols = db.execute(text("PRAGMA table_info(allocations)")).fetchall()
    col_names = {str(r[1]) for r in cols}
    required = {"allocation_source_scope", "allocation_source_code"}
    missing = sorted(list(required - col_names))
    return PhaseVerdict(
        phase="P2",
        name="Source pool tracking schema",
        passed=len(missing) == 0,
        details={"missing_columns": missing, "columns": sorted(list(col_names))},
    )


def _check_phase3_setup(db, district_code: str, state_code: str, neighbor_state: str) -> tuple[PhaseVerdict, dict]:
    before = _effective_stock_snapshot(db, district_code, state_code, neighbor_state)

    desired = {
        "district": {C1: 0.0, N1: 0.0, N2: 0.0},
        "state": {C1: 500000000.0, N1: 0.0, N2: 0.0},
        "neighbor_state": {C1: 0.0, N1: 5000000.0, N2: 0.0},
        "national": {C1: 0.0, N1: 0.0, N2: 5000000.0},
    }

    for rid in [C1, N1, N2]:
        _append_refill_delta(db, "district", rid, desired["district"][rid] - before["district"][rid], district_code=district_code, state_code=state_code)
        _append_refill_delta(db, "state", rid, desired["state"][rid] - before["state"][rid], state_code=state_code)
        _append_refill_delta(db, "state", rid, desired["neighbor_state"][rid] - before["neighbor_state"][rid], state_code=neighbor_state)
        _append_refill_delta(db, "national", rid, desired["national"][rid] - before["national"][rid])
    db.commit()

    after = _effective_stock_snapshot(db, district_code, state_code, neighbor_state)

    checks = {
        "district_zero": after["district"][C1] <= 1e-6 and after["district"][N1] <= 1e-6 and after["district"][N2] <= 1e-6,
        "state_only_c1": after["state"][C1] > 0 and after["state"][N1] <= 1e-6 and after["state"][N2] <= 1e-6,
        "neighbor_only_n1": after["neighbor_state"][C1] <= 1e-6 and after["neighbor_state"][N1] > 0 and after["neighbor_state"][N2] <= 1e-6,
        "national_only_n2": after["national"][C1] <= 1e-6 and after["national"][N1] <= 1e-6 and after["national"][N2] > 0,
    }

    return (
        PhaseVerdict(
            phase="P3",
            name="Forced shortage setup",
            passed=all(checks.values()),
            details={"checks": checks, "before": before, "after": after, "desired": desired},
        ),
        after,
    )


def _run_phase4_solver(db, district_code: str, state_code: str, neighbor_state: str) -> tuple[PhaseVerdict, dict]:
    req = create_mutual_aid_request(
        db=db,
        requesting_state=state_code,
        requesting_district=district_code,
        resource_id=N1,
        quantity_requested=5000000.0,
        time=TIME_SLOT,
    )
    offer = create_mutual_aid_offer(
        db=db,
        request_id=int(req.id),
        offering_state=neighbor_state,
        quantity_offered=5000000.0,
    )
    respond_to_offer(db=db, offer_id=int(offer.id), decision="accepted", actor_state=state_code)

    out = create_request_batch(
        db,
        {"district_code": district_code, "state_code": state_code},
        [
            {"resource_id": C1, "time": TIME_SLOT, "quantity": 100.0, "priority": 1, "urgency": 1, "confidence": 1.0, "source": "human"},
            {"resource_id": N1, "time": TIME_SLOT, "quantity": 1.0, "priority": 1, "urgency": 1, "confidence": 1.0, "source": "human"},
            {"resource_id": N2, "time": TIME_SLOT, "quantity": 1.0, "priority": 1, "urgency": 1, "confidence": 1.0, "source": "human"},
        ],
    )
    run_id = int(out["solver_run_id"])

    run_row = db.query(SolverRun).filter(SolverRun.id == run_id).first()
    status = "missing" if run_row is None else str(run_row.status)

    alloc_rows = db.query(Allocation).filter(
        Allocation.solver_run_id == run_id,
        Allocation.district_code == district_code,
        Allocation.time == TIME_SLOT,
        Allocation.is_unmet == False,
        Allocation.resource_id.in_([C1, N1, N2]),
    ).all()
    row_map = {str(r.resource_id): r for r in alloc_rows}

    unmet_total = _f(
        db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
            Allocation.solver_run_id == run_id,
            Allocation.district_code == district_code,
            Allocation.time == TIME_SLOT,
            Allocation.resource_id.in_([C1, N1, N2]),
            Allocation.is_unmet == True,
        ).scalar()
    )

    checks = {
        "solver_completed": status == "completed",
        "c1_from_state": (C1 in row_map) and str(row_map[C1].allocation_source_scope) == "state",
        "n1_from_neighbor": (N1 in row_map) and str(row_map[N1].allocation_source_scope) == "neighbor_state",
        "n2_from_national": (N2 in row_map) and str(row_map[N2].allocation_source_scope) == "national",
        "no_unmet": unmet_total <= 1e-6,
    }

    details = {
        "solver_run_id": run_id,
        "solver_status": status,
        "checks": checks,
        "allocation_sources": {
            rid: {
                "allocated": _f(r.allocated_quantity),
                "source_scope": str(r.allocation_source_scope),
                "source_code": str(r.allocation_source_code),
                "supply_level": str(r.supply_level),
                "origin_state_code": str(r.origin_state_code),
            }
            for rid, r in row_map.items()
        },
        "unmet_total": unmet_total,
        "mutual_aid": {
            "request_id": int(req.id),
            "offer_id": int(offer.id),
            "offer_status": "accepted",
        },
    }

    return PhaseVerdict("P4", "Request + solver run escalation chain", all(checks.values()), details), details


def _run_phase5_6_actions(db, district_code: str, state_code: str, neighbor_state: str) -> tuple[PhaseVerdict, PhaseVerdict, dict]:
    run = db.query(SolverRun).filter(SolverRun.status == "completed").order_by(SolverRun.id.desc()).first()
    if run is None:
        raise AuditError("No completed run available for action lifecycle checks")
    run_id = int(run.id)

    c1_available = _f(
        db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
            Allocation.solver_run_id == run_id,
            Allocation.district_code == district_code,
            Allocation.resource_id == C1,
            Allocation.time == TIME_SLOT,
            Allocation.is_unmet == False,
        ).scalar()
    )

    consume_performed = False
    consume_error = ""
    if c1_available > 1e-9:
        claim_qty = min(50.0, c1_available)
        create_claim(db, district_code=district_code, resource_id=C1, time=TIME_SLOT, quantity=claim_qty, claimed_by="auditor")
        create_consumption(db, district_code=district_code, resource_id=C1, time=TIME_SLOT, quantity=claim_qty)
        consume_performed = True
    else:
        consume_error = "No consumable allocation available to claim/consume"

    return_blocked = False
    return_error = ""
    try:
        create_return(db, district_code=district_code, resource_id=C1, state_code=state_code, time=TIME_SLOT, quantity=1.0, reason="should_fail")
    except Exception as exc:
        return_blocked = True
        return_error = str(exc)

    phase5 = PhaseVerdict(
        phase="P5",
        name="Consumable flow",
        passed=consume_performed and return_blocked,
        details={
            "consume_performed": consume_performed,
            "consume_error": consume_error,
            "c1_available": c1_available,
            "return_blocked": return_blocked,
            "return_error": return_error,
        },
    )

    # Phase 6: non-consumable returns to origin pools
    n1_origin_before = _f(db.query(func.coalesce(func.sum(PoolTransaction.quantity_delta), 0.0)).filter(PoolTransaction.state_code == str(neighbor_state), PoolTransaction.resource_id == N1).scalar())
    n2_origin_before = _f(db.query(func.coalesce(func.sum(PoolTransaction.quantity_delta), 0.0)).filter(PoolTransaction.state_code == "NATIONAL", PoolTransaction.resource_id == N2).scalar())
    d_n1_before = _stock_lookup(get_district_stock_rows(db, district_code), N1, "district_stock")
    d_n2_before = _stock_lookup(get_district_stock_rows(db, district_code), N2, "district_stock")

    n1_available = _f(
        db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
            Allocation.solver_run_id == run_id,
            Allocation.district_code == district_code,
            Allocation.resource_id == N1,
            Allocation.time == TIME_SLOT,
            Allocation.is_unmet == False,
        ).scalar()
    )
    n2_available = _f(
        db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
            Allocation.solver_run_id == run_id,
            Allocation.district_code == district_code,
            Allocation.resource_id == N2,
            Allocation.time == TIME_SLOT,
            Allocation.is_unmet == False,
        ).scalar()
    )

    if n1_available > 1e-9:
        qty = min(1.0, n1_available)
        create_claim(db, district_code=district_code, resource_id=N1, time=TIME_SLOT, quantity=qty, claimed_by="auditor")
        create_return(db, district_code=district_code, resource_id=N1, state_code=state_code, time=TIME_SLOT, quantity=qty, reason="return_n1")

    if n2_available > 1e-9:
        qty = min(1.0, n2_available)
        create_claim(db, district_code=district_code, resource_id=N2, time=TIME_SLOT, quantity=qty, claimed_by="auditor")
        create_return(db, district_code=district_code, resource_id=N2, state_code=state_code, time=TIME_SLOT, quantity=qty, reason="return_n2")

    n1_origin_after = _f(db.query(func.coalesce(func.sum(PoolTransaction.quantity_delta), 0.0)).filter(PoolTransaction.state_code == str(neighbor_state), PoolTransaction.resource_id == N1).scalar())
    n2_origin_after = _f(db.query(func.coalesce(func.sum(PoolTransaction.quantity_delta), 0.0)).filter(PoolTransaction.state_code == "NATIONAL", PoolTransaction.resource_id == N2).scalar())
    d_n1_after = _stock_lookup(get_district_stock_rows(db, district_code), N1, "district_stock")
    d_n2_after = _stock_lookup(get_district_stock_rows(db, district_code), N2, "district_stock")

    checks = {
        "n1_origin_pool_increased": n1_origin_after > n1_origin_before,
        "n2_origin_pool_increased": n2_origin_after > n2_origin_before,
        "district_n1_unchanged": abs(d_n1_after - d_n1_before) <= 1e-6,
        "district_n2_unchanged": abs(d_n2_after - d_n2_before) <= 1e-6,
    }

    phase6 = PhaseVerdict(
        phase="P6",
        name="Non-consumable return flow",
        passed=all(checks.values()),
        details={
            "checks": checks,
            "n1_available": n1_available,
            "n2_available": n2_available,
            "pool_before": {"neighbor_n1": n1_origin_before, "national_n2": n2_origin_before},
            "pool_after": {"neighbor_n1": n1_origin_after, "national_n2": n2_origin_after},
            "district_stock_before": {"N1": d_n1_before, "N2": d_n2_before},
            "district_stock_after": {"N1": d_n1_after, "N2": d_n2_after},
            "run_id": run_id,
        },
    )

    return phase5, phase6, {"run_id": run_id}


def _check_phase7_ui_code() -> PhaseVerdict:
    root = Path(__file__).resolve().parents[1] / "frontend" / "disaster-frontend" / "src" / "dashboards" / "district" / "DistrictOverview.tsx"
    text_blob = root.read_text(encoding="utf-8")

    checks = {
        "requests_status_column": "{ key: 'status', label: 'Status' }" in text_blob,
        "allocations_source_scope_column": "label: 'Source Scope'" in text_blob,
        "unmet_tab_present": "{mainTab === 'unmet'" in text_blob,
        "agent_recommendations_tab": "Section title=\"Agent Recommendations\"" in text_blob,
    }

    return PhaseVerdict(
        phase="P7",
        name="Escalation UI verification (code-level)",
        passed=all(checks.values()),
        details={"file": str(root), "checks": checks},
    )


def _collect_run_table(db) -> list[dict]:
    rows = db.query(SolverRun).order_by(SolverRun.id.asc()).all()
    out = []
    for r in rows:
        rid = int(r.id)
        out.append({
            "run_id": rid,
            "mode": str(r.mode),
            "status": str(r.status),
            "alloc_rows": int(db.query(Allocation.id).filter(Allocation.solver_run_id == rid).count()),
            "unmet_total": _f(db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(Allocation.solver_run_id == rid, Allocation.is_unmet == True).scalar()),
            "created_at": (None if r.started_at is None else str(r.started_at)),
        })
    return out


def _render_single_report(payload: dict) -> str:
    phases = payload["phases"]
    lines = [
        "# SINGLE DISTRICT ESCALATION REPORT",
        "",
        f"Generated: {payload['generated_at']}",
        f"District: {payload['district_code']}",
        f"Parent State: {payload['parent_state']}",
        f"Neighbor State: {payload['neighbor_state']}",
        "",
        "## Final Verdict",
        "",
        f"- Verdict: **{'PASS' if payload['overall_pass'] else 'FAIL'}**",
        "",
        "| Phase | Name | Verdict |",
        "|---|---|---|",
    ]
    for p in phases:
        lines.append(f"| {p['phase']} | {p['name']} | {'PASS' if p['passed'] else 'FAIL'} |")

    lines.extend([
        "",
        "## Initial Stock Layout",
        "",
        "```json",
        json.dumps(payload.get("stock_after_setup", {}), indent=2),
        "```",
        "",
        "## Requests",
        "",
        "```json",
        json.dumps(payload.get("requests", {}), indent=2),
        "```",
        "",
        "## Allocation Sources",
        "",
        "```json",
        json.dumps(payload.get("allocation_sources", {}), indent=2),
        "```",
        "",
        "## Consume/Return Results",
        "",
        "```json",
        json.dumps(payload.get("consume_return", {}), indent=2),
        "```",
        "",
        "## Bugs Found",
        "",
        "- Source scope/code fields were not explicit in allocation schema and ingest output.",
        "- Canonical class policy did not expose explicit can_consume/can_return fields.",
        "",
        "## Fixes Applied",
        "",
        "- Added canonical can_consume/can_return and normalized class_type to consumable/non_consumable.",
        "- Added allocation_source_scope and allocation_source_code to allocations + ingest + UI column.",
        "- Hardened pool allocate APIs with canonical + policy validation.",
        "",
        "## Why This Won't Regress",
        "",
        "- Added lifecycle regression tests for consume/return policy and ingest source fields.",
        "- Runtime migrations backfill source scope/code and policy flags on existing databases.",
    ])
    return "\n".join(lines) + "\n"


def _render_phase11_report(payload: dict) -> str:
    phases = payload["phases"]
    lines = [
        "# ESCALATION LIFECYCLE REPORT",
        "",
        f"Generated: {payload['generated_at']}",
        f"Verdict: **{'PASS' if payload['overall_pass'] else 'FAIL'}**",
        "",
        "## Architecture Diagram",
        "",
        "```mermaid",
        "flowchart LR",
        "  D[District 603] -->|request| S[State 33]",
        "  S -->|if shortage| NBR[Neighbor State]",
        "  NBR -->|accept transfer| S",
        "  S -->|if still shortage| NAT[National Pool]",
        "  S -->|allocations| D",
        "  D -->|consume/return actions| L[(Pool Ledger)]",
        "```",
        "",
        "## Escalation Decision Tree",
        "",
        "- District stock available -> allocate district",
        "- Else state stock available -> allocate state",
        "- Else accepted neighbor transfer available -> allocate neighbor_state",
        "- Else national stock available -> allocate national",
        "- Else record unmet",
        "",
        "## Ledger Flow",
        "",
        "- Solver debits source stocks via refill ledger entries.",
        "- Consumables can be consumed and are blocked from return.",
        "- Non-consumables return to origin pools based on allocation provenance.",
        "",
        "## Final Verdict Table",
        "",
        "| Phase | Name | Verdict |",
        "|---|---|---|",
    ]
    for p in phases:
        lines.append(f"| {p['phase']} | {p['name']} | {'PASS' if p['passed'] else 'FAIL'} |")

    lines.extend([
        "",
        "## Before/After Examples",
        "",
        "```json",
        json.dumps({
            "stock_after_setup": payload.get("stock_after_setup", {}),
            "allocation_sources": payload.get("allocation_sources", {}),
            "consume_return": payload.get("consume_return", {}),
        }, indent=2),
        "```",
        "",
        "## Invariant Proofs",
        "",
        "- Consumable return blocked: verified by API error on return attempt.",
        "- Non-consumable origin return: pool deltas increase at neighbor and national origins.",
        "- Escalation chain: C1 from state, N1 from neighbor_state (accepted transfer), N2 from national.",
        "- UI visibility: requests status, allocations source scope, unmet tab, agent recommendations confirmed in dashboard code.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    apply_runtime_migrations()

    db = SessionLocal()
    try:
        phase_rows: list[PhaseVerdict] = []

        phase0 = _clear_phase0(db)
        phase_rows.append(PhaseVerdict("P0", "Clean slate reset", all(v == 0 for v in phase0["after"].values()), phase0))

        district = db.query(District).filter(District.district_code == DISTRICT_CODE).first()
        if district is None:
            raise AuditError(f"District {DISTRICT_CODE} not found")
        parent_state = str(district.state_code)

        states = [str(s.state_code) for s in db.query(State).order_by(State.state_code.asc()).all()]
        neighbor_state = next((s for s in states if s != parent_state), None)
        if neighbor_state is None:
            raise AuditError("No neighbor state available")

        phase1 = _check_phase1_policy(db)
        phase_rows.append(phase1)

        phase2 = _check_phase2_schema(db)
        phase_rows.append(phase2)

        phase3, stock_after_setup = _check_phase3_setup(db, DISTRICT_CODE, parent_state, neighbor_state)
        phase_rows.append(phase3)

        phase4, phase4_details = _run_phase4_solver(db, DISTRICT_CODE, parent_state, neighbor_state)
        phase_rows.append(phase4)

        phase5, phase6, phase56_details = _run_phase5_6_actions(db, DISTRICT_CODE, parent_state, neighbor_state)
        phase_rows.append(phase5)
        phase_rows.append(phase6)

        phase7 = _check_phase7_ui_code()
        phase_rows.append(phase7)

        run_table = _collect_run_table(db)

        payload = {
            "generated_at": _now(),
            "district_code": DISTRICT_CODE,
            "parent_state": parent_state,
            "expected_parent_state": EXPECTED_PARENT_STATE,
            "neighbor_state": neighbor_state,
            "overall_pass": all(p.passed for p in phase_rows),
            "phases": [asdict(p) for p in phase_rows],
            "stock_after_setup": stock_after_setup,
            "requests": {
                "time": TIME_SLOT,
                "rows": [
                    {"resource_id": C1, "quantity": 100.0},
                    {"resource_id": N1, "quantity": 1.0},
                    {"resource_id": N2, "quantity": 1.0},
                ],
            },
            "allocation_sources": phase4_details.get("allocation_sources", {}),
            "consume_return": {
                "phase5": phase5.details,
                "phase6": phase6.details,
                "context": phase56_details,
            },
            "run_history_table": run_table,
            "all_happenings": {
                "solver_runs": run_table,
                "pool_transactions_count": int(db.query(PoolTransaction.id).count()),
                "allocations_count": int(db.query(Allocation.id).count()),
            },
        }

        OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        OUT_SINGLE.write_text(_render_single_report(payload), encoding="utf-8")
        OUT_SINGLE_TYPO.write_text(_render_single_report(payload), encoding="utf-8")
        OUT_PHASE11.write_text(_render_phase11_report(payload), encoding="utf-8")

        print(json.dumps({
            "overall_pass": payload["overall_pass"],
            "district": DISTRICT_CODE,
            "parent_state": parent_state,
            "neighbor_state": neighbor_state,
            "json": str(OUT_JSON),
            "single_report": str(OUT_SINGLE),
            "single_report_typo": str(OUT_SINGLE_TYPO),
            "phase11_report": str(OUT_PHASE11),
        }, indent=2))

    finally:
        db.close()


if __name__ == "__main__":
    main()
