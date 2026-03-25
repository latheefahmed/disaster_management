from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.database import SessionLocal
from app.models.scenario import Scenario
from app.models.scenario_request import ScenarioRequest
from app.models.solver_run import SolverRun
from app.models.district import District
from app.services.scenario_runner import run_scenario
from app.services.scenario_service import get_scenario_run_summary
from app.services.kpi_service import get_state_stock_rows
from app.services.mutual_aid_service import (
    AUTO_ESCALATION_MIN_UNMET_QTY,
    AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP,
    AUTO_ESCALATION_NEIGHBOR_MAX_STATES,
    get_candidate_states,
)


def _pick_valid_resource_for_district(db, district_code: str, state_code: str) -> str:
    from app.services.kpi_service import get_district_stock_rows

    try:
        drows = get_district_stock_rows(db, str(district_code))
    except Exception:
        return "R1"

    candidates = []
    for row in drows:
        rid = str(row.get("resource_id") or "")
        d_stock = float(row.get("district_stock") or 0.0)
        s_stock = float(row.get("state_stock") or 0.0)
        n_stock = float(row.get("national_stock") or 0.0)
        if rid and d_stock > 0.0 and s_stock > 0.0 and n_stock > 0.0:
            candidates.append((rid, d_stock + s_stock + n_stock))

    if not candidates:
        return "R1"
    candidates.sort(key=lambda x: x[1], reverse=True)
    return str(candidates[0][0])


def _resource_stock(db, state_code: str, resource_id: str) -> float:
    try:
        rows = get_state_stock_rows(db, str(state_code))
    except Exception:
        return 0.0
    for row in rows:
        if str(row.get("resource_id") or "") == str(resource_id):
            return float(row.get("state_stock") or 0.0)
    return 0.0


def _neighbor_diagnostic(db, summary: dict) -> dict:
    esc = dict(summary.get("escalation_status") or {})
    unmet_details = list(summary.get("unmet_details") or [])

    if int(esc.get("neighbor_offers_created") or 0) > 0:
        return {"neighbor_active": True, "reason": "offers_created"}

    if int(esc.get("state_marked") or 0) <= 0:
        return {"neighbor_active": False, "reason": "no_state_escalation_marked"}

    unmet_keys = {}
    for row in unmet_details:
        qty = float(row.get("unmet_quantity") or 0.0)
        if qty <= 1e-9:
            continue
        key = (
            str(row.get("state_code") or ""),
            str(row.get("resource_id") or ""),
            int(row.get("time") or 0),
        )
        unmet_keys[key] = unmet_keys.get(key, 0.0) + qty

    if not unmet_keys:
        return {"neighbor_active": False, "reason": "no_unmet_rows_after_summary"}

    limit = max(1, int(AUTO_ESCALATION_NEIGHBOR_MAX_STATES) * 2)
    min_offer_qty = float(AUTO_ESCALATION_MIN_UNMET_QTY)
    stock_cap = float(AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP)

    checks = []
    any_candidate_above_cap = False

    for (requesting_state, resource_id, time_slot), unmet_qty in unmet_keys.items():
        cands = get_candidate_states(db, requesting_state=requesting_state, limit=limit)
        cands = [c for c in cands if str(c.get("state_code") or "") != str(requesting_state)]
        cands = cands[: max(1, int(AUTO_ESCALATION_NEIGHBOR_MAX_STATES))]

        per_key = {
            "requesting_state": requesting_state,
            "resource_id": resource_id,
            "time": int(time_slot),
            "unmet_quantity": float(unmet_qty),
            "candidates": [],
        }

        for c in cands:
            s = str(c.get("state_code") or "")
            avail = _resource_stock(db, s, resource_id)
            max_offer = max(0.0, float(avail) * stock_cap)
            per_key["candidates"].append(
                {
                    "offering_state": s,
                    "state_stock": float(avail),
                    "max_offer_cap_qty": float(max_offer),
                    "distance_km": float(c.get("distance_km") or 0.0),
                }
            )
            if max_offer > min_offer_qty:
                any_candidate_above_cap = True

        checks.append(per_key)

    if not any_candidate_above_cap:
        return {
            "neighbor_active": False,
            "reason": "neighbor_candidates_below_cap_or_zero_stock",
            "stock_checks": checks,
        }

    return {
        "neighbor_active": False,
        "reason": "candidates_available_but_no_new_offer_created",
        "stock_checks": checks,
    }


def main():
    db = SessionLocal()
    now = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    try:
        district = db.query(District).filter(District.district_code == "347").first()
        if district is None:
            district = db.query(District).order_by(District.district_code.asc()).first()
        if district is None:
            raise RuntimeError("No district rows found")

        district_code = str(district.district_code)
        state_code = str(district.state_code)
        resource_id = "R13"
        print(f"SELECTED_DISTRICT={district_code}")
        print(f"SELECTED_STATE={state_code}")
        print(f"SELECTED_RESOURCE={resource_id}")
        print(f"NEIGHBOR_CANDIDATE_COUNT={len(get_candidate_states(db, requesting_state=state_code, limit=6))}")

        cases = [
            {
                "label": "C1_neighbor_potential_immediate",
                "rows": [
                    {"district_code": district_code, "state_code": state_code, "resource_id": resource_id, "time": 6, "quantity": 40000000.0},
                ],
            },
            {
                "label": "C2_neighbor_potential_staggered",
                "rows": [
                    {"district_code": district_code, "state_code": state_code, "resource_id": resource_id, "time": 7, "quantity": 30000000.0},
                ],
            },
            {
                "label": "C3_late_time_low_priority_national_path",
                "rows": [
                    {"district_code": district_code, "state_code": state_code, "resource_id": resource_id, "time": 24, "quantity": 30000000.0},
                ],
            },
            {
                "label": "C4_moderate_should_meet_local_then_upper",
                "rows": [
                    {"district_code": district_code, "state_code": state_code, "resource_id": resource_id, "time": 12, "quantity": 5000000.0},
                ],
            },
        ]

        outputs = []
        for idx, case in enumerate(cases, start=1):
            scenario = Scenario(name=f"AUTO_NEIGHBOR_LOGIC_{now}_{idx}_{case['label']}")
            db.add(scenario)
            db.commit()
            db.refresh(scenario)

            req_rows = []
            for row in case["rows"]:
                req = ScenarioRequest(
                    scenario_id=int(scenario.id),
                    district_code=str(row["district_code"]),
                    state_code=str(row["state_code"]),
                    resource_id=str(row["resource_id"]),
                    time=int(row["time"]),
                    quantity=float(row["quantity"]),
                )
                req_rows.append(req)
            db.bulk_save_objects(req_rows)
            db.commit()

            try:
                run_scenario(db, int(scenario.id), scope_mode="focused")
                run = db.query(SolverRun).filter(SolverRun.scenario_id == int(scenario.id)).order_by(SolverRun.id.desc()).first()
                if run is None:
                    raise RuntimeError(f"No solver run found for scenario {scenario.id}")

                summary = get_scenario_run_summary(db, int(scenario.id), int(run.id)) or {}
                neighbor_diag = _neighbor_diagnostic(db, summary)

                outputs.append(
                    {
                        "case": case["label"],
                        "scenario_id": int(scenario.id),
                        "run_id": int(run.id),
                        "status": str(run.status),
                        "requests": case["rows"],
                        "escalation_status": dict(summary.get("escalation_status") or {}),
                        "totals": dict(summary.get("totals") or {}),
                        "source_scope_breakdown": dict(summary.get("source_scope_breakdown") or {}),
                        "district_source_scope_breakdown": list(summary.get("district_source_scope_breakdown") or []),
                        "by_time_breakdown": list(summary.get("by_time_breakdown") or []),
                        "neighbor_diagnostic": neighbor_diag,
                    }
                )
            except Exception as exc:
                outputs.append(
                    {
                        "case": case["label"],
                        "scenario_id": int(scenario.id),
                        "run_id": None,
                        "status": "error",
                        "requests": case["rows"],
                        "error": str(exc),
                        "escalation_status": {},
                        "totals": {},
                        "source_scope_breakdown": {},
                        "district_source_scope_breakdown": [],
                        "by_time_breakdown": [],
                        "neighbor_diagnostic": {"neighbor_active": False, "reason": "solver_error"},
                    }
                )

        report_json = Path(f"SCENARIO_4_RUN_NEIGHBOR_DIAGNOSTICS_{now}.json")
        report_md = Path(f"SCENARIO_4_RUN_NEIGHBOR_DIAGNOSTICS_{now}.md")
        report_json.write_text(json.dumps(outputs, indent=2), encoding="utf-8")

        lines = [
            "# Scenario 4-Run Neighbor Diagnostics",
            "",
            f"Generated: {datetime.utcnow().isoformat()}Z",
            "",
        ]
        for out in outputs:
            esc = out.get("escalation_status") or {}
            scope = (out.get("source_scope_breakdown") or {}).get("allocations") or {}
            diag = out.get("neighbor_diagnostic") or {}
            lines.extend(
                [
                    f"## {out['case']} (scenario {out['scenario_id']}, run {out['run_id']})",
                    f"- Status: {out['status']}",
                    f"- Error: {out.get('error') or 'none'}",
                    f"- Escalation mode: {esc.get('mode')}",
                    f"- Escalation events found: {esc.get('events_found')}",
                    f"- State marked: {esc.get('state_marked')}",
                    f"- National marked: {esc.get('national_marked')}",
                    f"- Neighbor offers created: {esc.get('neighbor_offers_created')}",
                    f"- Neighbor offers accepted: {esc.get('neighbor_offers_accepted')}",
                    f"- Neighbor accepted quantity: {esc.get('neighbor_accepted_quantity')}",
                    f"- Total allocated: {(out.get('totals') or {}).get('allocated_quantity')}",
                    f"- Total unmet: {(out.get('totals') or {}).get('unmet_quantity')}",
                    f"- Source allocations: district={scope.get('district', 0.0)}, state={scope.get('state', 0.0)}, neighbor_state={scope.get('neighbor_state', 0.0)}, national={scope.get('national', 0.0)}",
                    f"- Neighbor diagnostic: {diag.get('reason')}",
                    "",
                ]
            )

        report_md.write_text("\n".join(lines), encoding="utf-8")

        print(f"REPORT_JSON={report_json}")
        print(f"REPORT_MD={report_md}")
        print("RUN_IDS=" + ",".join(str(o["run_id"]) for o in outputs))
    finally:
        db.close()


if __name__ == "__main__":
    main()
