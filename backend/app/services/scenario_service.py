from collections import defaultdict
import json

from sqlalchemy.orm import Session

from app.models.scenario import Scenario
from app.models.scenario_request import ScenarioRequest
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.solver_run import SolverRun
from app.models.scenario_explanation import ScenarioExplanation
from app.models.agent_recommendation import AgentRecommendation
from app.models.allocation import Allocation
from sqlalchemy import func


def create_scenario(db: Session, name: str):
    row = Scenario(name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_scenario_request(db: Session, scenario_id: int, data: dict):
    row = ScenarioRequest(
        scenario_id=scenario_id,
        district_code=data["district_code"],
        state_code=data["state_code"],
        resource_id=data["resource_id"],
        time=int(data["time"]),
        quantity=float(data["quantity"])
    )
    db.add(row)
    db.commit()
    return row


def add_scenario_demand_batch(db: Session, scenario_id: int, rows: list[dict]):
    if not rows:
        return {"inserted": 0}

    objects = []
    for data in rows:
        objects.append(ScenarioRequest(
            scenario_id=scenario_id,
            district_code=str(data["district_code"]),
            state_code=str(data["state_code"]),
            resource_id=str(data["resource_id"]),
            time=int(data["time"]),
            quantity=float(data["quantity"]),
        ))

    db.bulk_save_objects(objects)
    db.commit()
    return {"inserted": len(objects)}


def add_state_stock_override(db: Session, scenario_id: int, data: dict):
    row = ScenarioStateStock(
        scenario_id=scenario_id,
        state_code=data["state_code"],
        resource_id=data["resource_id"],
        quantity=float(data["quantity"])
    )
    db.add(row)
    db.commit()
    return row


def add_national_stock_override(db: Session, scenario_id: int, data: dict):
    row = ScenarioNationalStock(
        scenario_id=scenario_id,
        resource_id=data["resource_id"],
        quantity=float(data["quantity"])
    )
    db.add(row)
    db.commit()
    return row


def list_scenarios(db: Session):
    rows = db.query(Scenario).order_by(Scenario.id.desc()).all()
    result = []
    for row in rows:
        result.append({
            "id": row.id,
            "name": row.name,
            "status": row.status,
            "created_at": row.created_at,
            "demand_rows": db.query(ScenarioRequest).filter(ScenarioRequest.scenario_id == row.id).count(),
            "state_stock_rows": db.query(ScenarioStateStock).filter(ScenarioStateStock.scenario_id == row.id).count(),
            "national_stock_rows": db.query(ScenarioNationalStock).filter(ScenarioNationalStock.scenario_id == row.id).count(),
        })
    return result


def get_scenario_detail(db: Session, scenario_id: int):
    row = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not row:
        return None

    demand = db.query(ScenarioRequest).filter(ScenarioRequest.scenario_id == scenario_id).all()
    state_stock = db.query(ScenarioStateStock).filter(ScenarioStateStock.scenario_id == scenario_id).all()
    national_stock = db.query(ScenarioNationalStock).filter(ScenarioNationalStock.scenario_id == scenario_id).all()

    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "created_at": row.created_at,
        "demand": [
            {
                "id": d.id,
                "district_code": d.district_code,
                "state_code": d.state_code,
                "resource_id": d.resource_id,
                "time": d.time,
                "quantity": d.quantity,
            }
            for d in demand
        ],
        "state_stock": [
            {
                "id": s.id,
                "state_code": s.state_code,
                "resource_id": s.resource_id,
                "quantity": s.quantity,
            }
            for s in state_stock
        ],
        "national_stock": [
            {
                "id": n.id,
                "resource_id": n.resource_id,
                "quantity": n.quantity,
            }
            for n in national_stock
        ],
    }


def get_scenario_runs(db: Session, scenario_id: int):
    rows = db.query(SolverRun).filter(SolverRun.scenario_id == scenario_id).order_by(SolverRun.id.desc()).all()
    return [
        {
            "id": r.id,
            "status": r.status,
            "mode": r.mode,
            "started_at": r.started_at,
            "demand_snapshot_path": r.demand_snapshot_path,
        }
        for r in rows
    ]


def get_scenario_analysis(db: Session, scenario_id: int):
    explanations = db.query(ScenarioExplanation).filter(ScenarioExplanation.scenario_id == scenario_id).order_by(ScenarioExplanation.id.desc()).all()
    recommendations = db.query(AgentRecommendation).filter(AgentRecommendation.scenario_id == scenario_id).order_by(AgentRecommendation.id.desc()).all()

    return {
        "explanations": [
            {
                "id": e.id,
                "solver_run_id": e.solver_run_id,
                "summary": e.summary,
                "details": e.details,
                "created_at": e.created_at,
            }
            for e in explanations
        ],
        "recommendations": [
            {
                "id": r.id,
                "solver_run_id": r.solver_run_id,
                "district_code": r.district_code,
                "resource_id": r.resource_id,
                "action_type": r.action_type,
                "message": r.message,
                "requires_confirmation": r.requires_confirmation,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in recommendations
        ],
    }


def get_scenario_run_summary(db: Session, scenario_id: int, run_id: int):
    run = db.query(SolverRun).filter(
        SolverRun.id == run_id,
        SolverRun.scenario_id == scenario_id,
    ).first()
    if not run:
        return None

    if getattr(run, "summary_snapshot_json", None):
        try:
            snap = json.loads(str(run.summary_snapshot_json))
            if isinstance(snap, dict):
                national_rows = list(snap.get("national_allocation_summary_rows") or [])
                totals = dict(snap.get("totals") or {})
                by_time = list(snap.get("by_time_breakdown") or [])
                fairness = dict(snap.get("fairness") or {})
                source_scope = dict((snap.get("source_scope_breakdown") or {}).get("allocations") or {})

                districts = sorted({str(r.get("district_code") or "") for r in national_rows if str(r.get("district_code") or "")})
                district_breakdown = []
                for district in districts:
                    d_alloc = sum(float(r.get("allocated_quantity") or 0.0) for r in national_rows if str(r.get("district_code") or "") == district)
                    d_unmet = sum(float(r.get("unmet_quantity") or 0.0) for r in national_rows if str(r.get("district_code") or "") == district)
                    district_breakdown.append(
                        {
                            "district_code": district,
                            "allocated_quantity": d_alloc,
                            "unmet_quantity": d_unmet,
                            "met": d_unmet <= 1e-9,
                        }
                    )

                return {
                    "run_id": run.id,
                    "scenario_id": scenario_id,
                    "status": run.status,
                    "started_at": run.started_at,
                    "totals": {
                        "allocated_quantity": float(totals.get("allocated_quantity") or 0.0),
                        "unmet_quantity": float(totals.get("unmet_quantity") or 0.0),
                        "districts_covered": int(totals.get("districts_covered") or len(districts)),
                        "districts_met": sum(1 for r in district_breakdown if bool(r.get("met"))),
                        "districts_unmet": sum(1 for r in district_breakdown if not bool(r.get("met"))),
                        "allocation_rows": len(national_rows),
                        "unmet_rows": len([r for r in national_rows if float(r.get("unmet_quantity") or 0.0) > 1e-9]),
                    },
                    "district_breakdown": district_breakdown,
                    "source_scope_breakdown": {
                        "allocations": {
                            "district": float(source_scope.get("district") or 0.0),
                            "state": float(source_scope.get("state") or 0.0),
                            "neighbor_state": float(source_scope.get("neighbor_state") or 0.0),
                            "national": float(source_scope.get("national") or 0.0),
                        },
                        "percentages": dict((snap.get("source_scope_breakdown") or {}).get("percentages") or {}),
                    },
                    "by_time_breakdown": by_time,
                    "fairness": {
                        "district_ratio_jain": fairness.get("district_ratio_jain"),
                        "state_ratio_jain": fairness.get("state_ratio_jain"),
                        "district_ratio_gap": fairness.get("district_ratio_gap"),
                        "state_ratio_gap": fairness.get("state_ratio_gap"),
                        "time_service_early_avg": None,
                        "time_service_late_avg": None,
                        "fairness_flags": [],
                    },
                    "allocation_details": [
                        {
                            "district_code": str(r.get("district_code") or ""),
                            "state_code": str(r.get("state_code") or ""),
                            "resource_id": str(r.get("resource_id") or ""),
                            "time": int(r.get("time") or 0),
                            "allocated_quantity": float(r.get("allocated_quantity") or 0.0),
                        }
                        for r in national_rows
                    ],
                    "unmet_details": [
                        {
                            "district_code": str(r.get("district_code") or ""),
                            "state_code": str(r.get("state_code") or ""),
                            "resource_id": str(r.get("resource_id") or ""),
                            "time": int(r.get("time") or 0),
                            "unmet_quantity": float(r.get("unmet_quantity") or 0.0),
                        }
                        for r in national_rows
                        if float(r.get("unmet_quantity") or 0.0) > 1e-9
                    ],
                }
        except Exception:
            pass

    alloc_rows = db.query(
        Allocation.district_code,
        Allocation.state_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("quantity"),
    ).filter(
        Allocation.solver_run_id == run_id,
        Allocation.is_unmet == False,
    ).group_by(
        Allocation.district_code,
        Allocation.state_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    unmet_rows = db.query(
        Allocation.district_code,
        Allocation.state_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("quantity"),
    ).filter(
        Allocation.solver_run_id == run_id,
        Allocation.is_unmet == True,
    ).group_by(
        Allocation.district_code,
        Allocation.state_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    by_district_alloc: dict[str, float] = {}
    by_district_unmet: dict[str, float] = {}

    for row in alloc_rows:
        district = str(row.district_code)
        by_district_alloc[district] = by_district_alloc.get(district, 0.0) + float(row.quantity or 0.0)

    for row in unmet_rows:
        district = str(row.district_code)
        by_district_unmet[district] = by_district_unmet.get(district, 0.0) + float(row.quantity or 0.0)

    by_state_alloc: dict[str, float] = defaultdict(float)
    by_state_unmet: dict[str, float] = defaultdict(float)
    by_time_alloc: dict[int, float] = defaultdict(float)
    by_time_unmet: dict[int, float] = defaultdict(float)

    for row in alloc_rows:
        state_code = str(row.state_code or "")
        by_state_alloc[state_code] += float(row.quantity or 0.0)
        by_time_alloc[int(row.time)] += float(row.quantity or 0.0)

    for row in unmet_rows:
        state_code = str(row.state_code or "")
        by_state_unmet[state_code] += float(row.quantity or 0.0)
        by_time_unmet[int(row.time)] += float(row.quantity or 0.0)

    scope_rows = db.query(
        func.coalesce(Allocation.allocation_source_scope, "").label("source_scope"),
        func.coalesce(Allocation.supply_level, "district").label("supply_level"),
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("quantity"),
    ).filter(
        Allocation.solver_run_id == run_id,
        Allocation.is_unmet == False,
    ).group_by(
        Allocation.allocation_source_scope,
        Allocation.supply_level,
    ).all()

    scope_allocations = {
        "district": 0.0,
        "state": 0.0,
        "neighbor_state": 0.0,
        "national": 0.0,
    }
    for row in scope_rows:
        raw_scope = str(row.source_scope or "").strip().lower()
        raw_level = str(row.supply_level or "district").strip().lower()
        key = raw_scope if raw_scope in scope_allocations else raw_level
        if key not in scope_allocations:
            key = "district"
        scope_allocations[key] += float(row.quantity or 0.0)

    def _jain(values: list[float]) -> float | None:
        clean = [max(0.0, float(v)) for v in values]
        if not clean:
            return None
        numerator = sum(clean) ** 2
        denominator = float(len(clean)) * sum(v * v for v in clean)
        if denominator <= 1e-12:
            return None
        return float(numerator / denominator)

    district_service_ratios = [
        (float(by_district_alloc.get(d, 0.0)) / float(by_district_alloc.get(d, 0.0) + by_district_unmet.get(d, 0.0)))
        for d in sorted(set(list(by_district_alloc.keys()) + list(by_district_unmet.keys())))
        if float(by_district_alloc.get(d, 0.0) + by_district_unmet.get(d, 0.0)) > 1e-9
    ]
    state_service_ratios = [
        (float(by_state_alloc.get(s, 0.0)) / float(by_state_alloc.get(s, 0.0) + by_state_unmet.get(s, 0.0)))
        for s in sorted(set(list(by_state_alloc.keys()) + list(by_state_unmet.keys())))
        if float(by_state_alloc.get(s, 0.0) + by_state_unmet.get(s, 0.0)) > 1e-9
    ]

    by_time_breakdown: list[dict] = []
    times = sorted(set(list(by_time_alloc.keys()) + list(by_time_unmet.keys())))
    for t in times:
        met = float(by_time_alloc.get(t, 0.0))
        unmet = float(by_time_unmet.get(t, 0.0))
        demand = met + unmet
        service_ratio = (met / demand) if demand > 1e-9 else 1.0
        by_time_breakdown.append(
            {
                "time": int(t),
                "demand_quantity": float(demand),
                "allocated_quantity": float(met),
                "unmet_quantity": float(unmet),
                "service_ratio": float(service_ratio),
            }
        )

    pivot = len(by_time_breakdown) // 2
    early_ratios = [x["service_ratio"] for idx, x in enumerate(by_time_breakdown) if idx <= pivot]
    late_ratios = [x["service_ratio"] for idx, x in enumerate(by_time_breakdown) if idx > pivot]
    early_avg = (sum(early_ratios) / len(early_ratios)) if early_ratios else None
    late_avg = (sum(late_ratios) / len(late_ratios)) if late_ratios else None

    district_jain = _jain(district_service_ratios)
    state_jain = _jain(state_service_ratios)
    district_gap = (max(district_service_ratios) - min(district_service_ratios)) if district_service_ratios else None
    state_gap = (max(state_service_ratios) - min(state_service_ratios)) if state_service_ratios else None

    fairness_flags: list[str] = []
    if district_jain is not None and district_jain < 0.85:
        fairness_flags.append("district_fairness_low")
    if state_jain is not None and state_jain < 0.80:
        fairness_flags.append("state_fairness_low")
    if district_gap is not None and district_gap > 0.45:
        fairness_flags.append("district_gap_high")
    if early_avg is not None and late_avg is not None and early_avg + 0.05 < late_avg:
        fairness_flags.append("time_index_priority_violation")

    districts_in_run = sorted(set(list(by_district_alloc.keys()) + list(by_district_unmet.keys())))
    districts_met = sum(1 for d in districts_in_run if by_district_unmet.get(d, 0.0) <= 1e-9)

    alloc_details = [
        {
            "district_code": str(r.district_code),
            "state_code": str(r.state_code),
            "resource_id": str(r.resource_id),
            "time": int(r.time),
            "allocated_quantity": float(r.quantity or 0.0),
        }
        for r in alloc_rows
    ]
    unmet_details = [
        {
            "district_code": str(r.district_code),
            "state_code": str(r.state_code),
            "resource_id": str(r.resource_id),
            "time": int(r.time),
            "unmet_quantity": float(r.quantity or 0.0),
        }
        for r in unmet_rows
    ]

    return {
        "run_id": run.id,
        "scenario_id": scenario_id,
        "status": run.status,
        "started_at": run.started_at,
        "totals": {
            "allocated_quantity": float(sum(by_district_alloc.values())),
            "unmet_quantity": float(sum(by_district_unmet.values())),
            "districts_covered": len(districts_in_run),
            "districts_met": districts_met,
            "districts_unmet": len(districts_in_run) - districts_met,
            "allocation_rows": len(alloc_details),
            "unmet_rows": len(unmet_details),
        },
        "district_breakdown": [
            {
                "district_code": d,
                "allocated_quantity": float(by_district_alloc.get(d, 0.0)),
                "unmet_quantity": float(by_district_unmet.get(d, 0.0)),
                "met": by_district_unmet.get(d, 0.0) <= 1e-9,
            }
            for d in districts_in_run
        ],
        "source_scope_breakdown": {
            "allocations": {
                k: float(v)
                for k, v in scope_allocations.items()
            },
            "percentages": {
                k: float((v / sum(scope_allocations.values())) if sum(scope_allocations.values()) > 1e-9 else 0.0)
                for k, v in scope_allocations.items()
            },
        },
        "by_time_breakdown": by_time_breakdown,
        "fairness": {
            "district_ratio_jain": district_jain,
            "state_ratio_jain": state_jain,
            "district_ratio_gap": district_gap,
            "state_ratio_gap": state_gap,
            "time_service_early_avg": early_avg,
            "time_service_late_avg": late_avg,
            "fairness_flags": fairness_flags,
        },
        "allocation_details": alloc_details,
        "unmet_details": unmet_details,
    }


def get_scenario_run_incidents(db: Session, scenario_id: int, limit: int = 50):
    cap = max(1, min(200, int(limit or 50)))
    runs = db.query(SolverRun).filter(SolverRun.scenario_id == int(scenario_id)).order_by(SolverRun.id.desc()).limit(cap).all()

    incidents: list[dict] = []
    for run in runs:
        summary = get_scenario_run_summary(db, int(scenario_id), int(run.id))
        if not summary:
            continue

        fairness = summary.get("fairness") or {}
        flags = list(fairness.get("fairness_flags") or [])
        totals = summary.get("totals") or {}
        unmet = float(totals.get("unmet_quantity") or 0.0)
        scope_alloc = ((summary.get("source_scope_breakdown") or {}).get("allocations") or {})
        neighbor_qty = float(scope_alloc.get("neighbor_state") or 0.0)

        reasons: list[str] = []
        if unmet > 0.0:
            reasons.append("unmet_present")
        if "time_index_priority_violation" in flags:
            reasons.append("time_index_priority_violation")
        if "district_fairness_low" in flags or "state_fairness_low" in flags:
            reasons.append("fairness_low")
        if neighbor_qty > 0.0:
            reasons.append("neighbor_state_used")

        if not reasons:
            continue

        incidents.append(
            {
                "run_id": int(run.id),
                "status": str(run.status or ""),
                "started_at": run.started_at,
                "reasons": reasons,
                "unmet_quantity": unmet,
                "districts_unmet": int(totals.get("districts_unmet") or 0),
                "time_service_early_avg": fairness.get("time_service_early_avg"),
                "time_service_late_avg": fairness.get("time_service_late_avg"),
                "fairness_flags": flags,
                "scope_allocations": {
                    "district": float(scope_alloc.get("district") or 0.0),
                    "state": float(scope_alloc.get("state") or 0.0),
                    "neighbor_state": float(scope_alloc.get("neighbor_state") or 0.0),
                    "national": float(scope_alloc.get("national") or 0.0),
                },
            }
        )

    return {
        "scenario_id": int(scenario_id),
        "scanned_runs": len(runs),
        "incident_count": len(incidents),
        "incidents": incidents,
    }
