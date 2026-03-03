import pandas as pd
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.models.request import ResourceRequest
from app.models.scenario_request import ScenarioRequest
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.scenario import Scenario
from app.models.district import District
from app.models.solver_run import SolverRun
from app.models.allocation import Allocation
from app.models.audit_log import AuditLog
from app.models.scenario_explanation import ScenarioExplanation
from app.models.agent_recommendation import AgentRecommendation

from app.engine_bridge.solver_runner import run_solver
from app.engine_bridge.ingest import ingest_solver_results
from app.engine_bridge.solver_lock import solver_execution_lock
from app.config import CORE_ENGINE_ROOT, PHASE3_OUTPUT_PATH, ENABLE_MUTUAL_AID, PHASE4_RESOURCE_DATA
from app.services.final_demand_service import persist_final_demands
from app.services.demand_learning_service import (
    apply_weight_models_to_merged_demand,
    capture_demand_learning_events,
)
from app.services.priority_urgency_ml_service import get_latest_priority_urgency_model_refs
from app.services.priority_urgency_ml_service import capture_priority_urgency_events_for_scenario
from app.services.run_snapshot_service import persist_solver_run_snapshot
from app.services.audit_service import log_event
from app.services.mutual_aid_service import (
    build_state_stock_with_confirmed_transfers,
    mark_confirmed_transfers_consumed,
    apply_transfer_provenance_to_run,
)


def _extract_scenario_scope(scenario_human_df: pd.DataFrame) -> dict[str, set[str]]:
    if scenario_human_df is None or scenario_human_df.empty:
        return {"districts": set(), "resources": set(), "times": set()}

    districts = set(scenario_human_df["district_code"].astype(str).unique().tolist()) if "district_code" in scenario_human_df.columns else set()
    resources = set(scenario_human_df["resource_id"].astype(str).unique().tolist()) if "resource_id" in scenario_human_df.columns else set()
    times = set(int(t) for t in scenario_human_df["time"].astype(int).unique().tolist()) if "time" in scenario_human_df.columns else set()
    return {
        "districts": districts,
        "resources": resources,
        "times": times,
    }


def _filter_baseline_to_scope(baseline_df: pd.DataFrame, scope: dict[str, set[str]]) -> pd.DataFrame:
    if baseline_df is None or baseline_df.empty:
        return pd.DataFrame(columns=["district_code", "resource_id", "time", "demand"])

    filtered = baseline_df.copy()

    districts = scope.get("districts") or set()
    resources = scope.get("resources") or set()
    times = scope.get("times") or set()

    if districts:
        filtered = filtered[filtered["district_code"].astype(str).isin(districts)]
    if resources:
        filtered = filtered[filtered["resource_id"].astype(str).isin(resources)]
    if times:
        filtered = filtered[filtered["time"].astype(int).isin({int(t) for t in times})]

    return _normalize_demand_frame(filtered)


def _assert_scope_subset(df: pd.DataFrame, selected_districts: set[str], label: str):
    if df is None or df.empty:
        return
    if not selected_districts:
        raise ValueError(f"preflight_failed:{label}:selected_districts_empty")

    districts_in_df = set(df["district_code"].astype(str).unique().tolist())
    rogue = sorted([d for d in districts_in_df if d not in selected_districts])
    if rogue:
        raise ValueError(
            f"preflight_failed:{label}:district_scope_breach:count={len(rogue)}:sample={rogue[:10]}"
        )


# ============================================================
# VALIDATION
# ============================================================

def _validate_demand(df: pd.DataFrame):

    if df.empty:
        return

    if (df["demand"] < 0).any():
        raise ValueError("Negative demand detected")


def _normalize_demand_frame(df: pd.DataFrame, value_col: str = "demand") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["district_code", "resource_id", "time", "demand"])

    work = df.copy()

    if value_col != "demand" and value_col in work.columns:
        work = work.rename(columns={value_col: "demand"})

    required = {"district_code", "resource_id", "time", "demand"}
    if not required.issubset(work.columns):
        return pd.DataFrame(columns=["district_code", "resource_id", "time", "demand"])

    work["district_code"] = work["district_code"].astype(str)
    work["resource_id"] = work["resource_id"].astype(str)
    work["time"] = work["time"].astype(int)
    work["demand"] = work["demand"].astype(float)

    work = work.groupby(
        ["district_code", "resource_id", "time"],
        as_index=False
    )["demand"].sum()

    return work


def _load_baseline_demand() -> pd.DataFrame:
    baseline_path = PHASE3_OUTPUT_PATH / "district_resource_demand.csv"
    baseline_df = pd.read_csv(baseline_path)
    return _normalize_demand_frame(baseline_df, value_col="demand")


def _get_district_mode_map(db: Session) -> dict[str, str]:
    return {
        str(d.district_code): str(d.demand_mode or "baseline_plus_human")
        for d in db.query(District).all()
    }


def _assemble_final_demand(
    db: Session,
    baseline_df: pd.DataFrame,
    human_df: pd.DataFrame,
    include_model_ids: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, list[int]]:

    base = _normalize_demand_frame(baseline_df)
    human = _normalize_demand_frame(human_df)

    merged = base.merge(
        human,
        on=["district_code", "resource_id", "time"],
        how="outer",
        suffixes=("_baseline", "_human")
    )

    merged["demand_baseline"] = merged["demand_baseline"].fillna(0.0)
    merged["demand_human"] = merged["demand_human"].fillna(0.0)

    mode_map = _get_district_mode_map(db)
    merged["demand_mode"] = merged["district_code"].map(mode_map).fillna("baseline_plus_human")

    merged["demand"] = merged["demand_baseline"] + merged["demand_human"]

    weighted_merged, used_model_ids = apply_weight_models_to_merged_demand(db, merged)
    merged = weighted_merged

    merged.loc[merged["demand_mode"] == "human_only", "demand"] = merged["demand_human"]
    merged.loc[merged["demand_mode"] == "baseline_only", "demand"] = merged["demand_baseline"]

    learned_mask = (
        (merged["demand_mode"] == "baseline_plus_human")
        & (merged["source_mix"] == "learned_weighted")
    )

    merged["source_mix"] = "merged"
    merged.loc[learned_mask, "source_mix"] = "learned_weighted"
    merged.loc[merged["demand_mode"] == "human_only", "source_mix"] = "human"
    merged.loc[merged["demand_mode"] == "baseline_only", "source_mix"] = "baseline"

    merged = merged[merged["demand"] > 0]

    final_df = merged[["district_code", "resource_id", "time", "demand", "demand_mode", "source_mix"]].copy()

    final_df = final_df.groupby(
        ["district_code", "resource_id", "time", "demand_mode", "source_mix"],
        as_index=False
    )["demand"].sum()

    _validate_demand(final_df)
    if include_model_ids:
        return final_df, used_model_ids
    return final_df


def _build_scenario_human_signal(db: Session, scenario_id: int) -> pd.DataFrame:
    rows = db.query(ScenarioRequest).filter(ScenarioRequest.scenario_id == scenario_id).all()

    if not rows:
        return pd.DataFrame(columns=["district_code", "resource_id", "time", "demand"])

    raw = pd.DataFrame([{
        "district_code": r.district_code,
        "resource_id": r.resource_id,
        "time": r.time,
        "demand": r.quantity
    } for r in rows])

    return _normalize_demand_frame(raw)


def _build_state_stock_override_file(db: Session, scenario_id: int) -> str | None:
    rows = db.query(ScenarioStateStock).filter(ScenarioStateStock.scenario_id == scenario_id).all()

    if not rows:
        return None

    path = CORE_ENGINE_ROOT / "phase4" / "scenarios" / "generated" / f"scenario_{scenario_id}_state_stock.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame([{
        "state_code": r.state_code,
        "resource_id": r.resource_id,
        "quantity": float(r.quantity)
    } for r in rows]).to_csv(path, index=False)

    return str(path)


def _build_national_stock_override_file(db: Session, scenario_id: int) -> str | None:
    rows = db.query(ScenarioNationalStock).filter(ScenarioNationalStock.scenario_id == scenario_id).all()

    if not rows:
        return None

    path = CORE_ENGINE_ROOT / "phase4" / "scenarios" / "generated" / f"scenario_{scenario_id}_national_stock.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame([{
        "resource_id": r.resource_id,
        "quantity": float(r.quantity)
    } for r in rows]).to_csv(path, index=False)

    return str(path)


def _write_agent_outputs(
    db: Session,
    scenario_id: int,
    solver_run_id: int,
    baseline_df: pd.DataFrame,
    human_df: pd.DataFrame,
    final_df: pd.DataFrame
):
    alloc = db.query(Allocation).filter(Allocation.solver_run_id == solver_run_id).all()

    alloc_df = pd.DataFrame([{
        "district_code": a.district_code,
        "resource_id": a.resource_id,
        "time": int(a.time),
        "allocated_quantity": float(a.allocated_quantity),
        "is_unmet": bool(a.is_unmet)
    } for a in alloc]) if alloc else pd.DataFrame(columns=["district_code", "resource_id", "time", "allocated_quantity", "is_unmet"])

    unmet_df = alloc_df[alloc_df["is_unmet"] == True].copy() if not alloc_df.empty else pd.DataFrame(columns=["district_code", "resource_id", "allocated_quantity"])

    unmet_agg = unmet_df.groupby(["district_code", "resource_id"], as_index=False)["allocated_quantity"].sum() if not unmet_df.empty else pd.DataFrame(columns=["district_code", "resource_id", "allocated_quantity"])

    base_agg = baseline_df.groupby(["district_code", "resource_id"], as_index=False)["demand"].sum()
    human_agg = human_df.groupby(["district_code", "resource_id"], as_index=False)["demand"].sum() if not human_df.empty else pd.DataFrame(columns=["district_code", "resource_id", "demand"])

    recs = []

    priority_unmet = unmet_agg.sort_values("allocated_quantity", ascending=False).head(200)

    for row in priority_unmet.itertuples(index=False):
        recs.append(AgentRecommendation(
            scenario_id=scenario_id,
            solver_run_id=solver_run_id,
            district_code=str(row.district_code),
            resource_id=str(row.resource_id),
            action_type="auto_adjust_urgency",
            message=f"Suggest urgency escalation for unmet resource {row.resource_id} in district {row.district_code}",
            requires_confirmation=False,
            status="open"
        ))

        recs.append(AgentRecommendation(
            scenario_id=scenario_id,
            solver_run_id=solver_run_id,
            district_code=str(row.district_code),
            resource_id=str(row.resource_id),
            action_type="auto_adjust_priority",
            message=f"Suggest priority increase for resource {row.resource_id} in district {row.district_code}",
            requires_confirmation=False,
            status="open"
        ))

    if not human_agg.empty:
        compare = human_agg.merge(
            base_agg,
            on=["district_code", "resource_id"],
            how="left",
            suffixes=("_human", "_baseline")
        )
        compare["demand_baseline"] = compare["demand_baseline"].fillna(0.0)

        compare["signal_ratio"] = compare["demand_human"] / compare["demand_baseline"].replace({0.0: 1.0})
        compare = compare.sort_values(["signal_ratio", "demand_human"], ascending=False).head(100)

        for row in compare.itertuples(index=False):
            baseline_val = float(row.demand_baseline)
            human_val = float(row.demand_human)
            if human_val > max(1000.0, 5.0 * max(1.0, baseline_val)):
                recs.append(AgentRecommendation(
                    scenario_id=scenario_id,
                    solver_run_id=solver_run_id,
                    district_code=str(row.district_code),
                    resource_id=str(row.resource_id),
                    action_type="ask_human_confirmation",
                    message=f"Flag potentially unrealistic human request for {row.resource_id} in district {row.district_code}: {human_val:.2f}",
                    requires_confirmation=True,
                    status="open"
                ))

    if not unmet_agg.empty:
        heavy_unmet = unmet_agg.sort_values("allocated_quantity", ascending=False).head(5)
        for row in heavy_unmet.itertuples(index=False):
            recs.append(AgentRecommendation(
                scenario_id=scenario_id,
                solver_run_id=solver_run_id,
                district_code=str(row.district_code),
                resource_id=str(row.resource_id),
                action_type="suggest_baseline_multiplier",
                message=f"Increase baseline weight for {row.resource_id} in district {row.district_code}",
                requires_confirmation=True,
                status="open"
            ))

        top_district = heavy_unmet.iloc[0]["district_code"]
        recs.append(AgentRecommendation(
            scenario_id=scenario_id,
            solver_run_id=solver_run_id,
            district_code=str(top_district),
            resource_id=None,
            action_type="lock_human_only_temporarily",
            message=f"Consider locking district {top_district} to human_only temporarily for next run",
            requires_confirmation=True,
            status="open"
        ))

    if recs:
        db.bulk_save_objects(recs)

    total_demand = float(final_df["demand"].sum()) if not final_df.empty else 0.0
    total_unmet = float(unmet_df["allocated_quantity"].sum()) if not unmet_df.empty else 0.0

    explanation = ScenarioExplanation(
        scenario_id=scenario_id,
        solver_run_id=solver_run_id,
        summary=(
            f"Scenario {scenario_id} completed. "
            f"Total demand={total_demand:.2f}, unmet={total_unmet:.2f}, "
            f"recommendations={len(recs)}"
        ),
        details={
            "total_demand": total_demand,
            "total_unmet": total_unmet,
            "recommendation_count": len(recs)
        }
    )
    db.add(explanation)

    db.add(AuditLog(
        actor_role="agent",
        actor_id="human_loop_agent",
        event_type="SCENARIO_ANALYSIS_COMPLETED",
        payload={
            "scenario_id": scenario_id,
            "solver_run_id": solver_run_id,
            "recommendation_count": len(recs),
            "total_unmet": total_unmet
        }
    ))

    db.commit()


# ============================================================
# LIVE HUMAN DEMAND SNAPSHOT
# (RETURNS DATAFRAME — NOT PATH)
# ============================================================

def build_live_demand_snapshot(db: Session) -> pd.DataFrame:
    latest_completed_live = db.query(SolverRun).filter(
        SolverRun.mode == "live",
        SolverRun.status == "completed",
    ).order_by(SolverRun.id.desc()).first()

    latest_completed_any = db.query(SolverRun).filter(
        SolverRun.status == "completed",
    ).order_by(SolverRun.id.desc()).first()

    latest_completed_run = latest_completed_live or latest_completed_any

    query = db.query(ResourceRequest).filter(
        ResourceRequest.status.in_(["pending", "escalated_national", "escalated_state"]),
        (ResourceRequest.included_in_run == 0) | (ResourceRequest.included_in_run.is_(None)),
        ResourceRequest.run_id == 0,
    )

    if latest_completed_run and latest_completed_run.started_at is not None:
        query = query.filter(ResourceRequest.created_at >= latest_completed_run.started_at)

    rows = query.all()

    data = []

    for r in rows:
        data.append({
            "district_code": r.district_code,
            "resource_id": r.resource_id,
            "time": r.time,
            "demand": r.quantity
        })

    if not data:
        df = pd.DataFrame(columns=["district_code", "resource_id", "time", "demand"])
    else:
        df = pd.DataFrame(data)
        df = _normalize_demand_frame(df)

    _validate_demand(df)

    snapshot_path = CORE_ENGINE_ROOT / "phase4" / "scenarios" / "generated" / "human_demand_snapshot.csv"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(snapshot_path, index=False)

    return df


def _preflight_validate_scenario_run(
    db: Session,
    scenario_id: int,
    baseline_df: pd.DataFrame,
    scenario_human_df: pd.DataFrame,
    final_df: pd.DataFrame,
):
    if scenario_human_df is None or scenario_human_df.empty:
        raise ValueError("preflight_failed:no_scenario_requests")

    if final_df is None or final_df.empty:
        raise ValueError("preflight_failed:final_demand_empty")

    scenario_rows = int(len(scenario_human_df.index))
    scenario_total = float(scenario_human_df["demand"].sum()) if "demand" in scenario_human_df.columns else 0.0
    if scenario_rows <= 0 or scenario_total <= 0.0:
        raise ValueError("preflight_failed:scenario_signal_non_positive")

    negative_state = db.query(ScenarioStateStock).filter(
        ScenarioStateStock.scenario_id == int(scenario_id),
        ScenarioStateStock.quantity < 0,
    ).first()
    if negative_state is not None:
        raise ValueError("preflight_failed:negative_state_stock_override")

    negative_national = db.query(ScenarioNationalStock).filter(
        ScenarioNationalStock.scenario_id == int(scenario_id),
        ScenarioNationalStock.quantity < 0,
    ).first()
    if negative_national is not None:
        raise ValueError("preflight_failed:negative_national_stock_override")

    baseline_resources = set(baseline_df["resource_id"].astype(str).unique().tolist()) if baseline_df is not None and not baseline_df.empty else set()
    scenario_resources = set(scenario_human_df["resource_id"].astype(str).unique().tolist()) if "resource_id" in scenario_human_df.columns else set()
    unknown_resources = sorted([rid for rid in scenario_resources if rid not in baseline_resources])
    if unknown_resources:
        log_event(
            actor_role="system",
            actor_id="scenario_runner",
            event_type="SCENARIO_PREFLIGHT_RESOURCE_WARNING",
            payload={
                "scenario_id": int(scenario_id),
                "unknown_resources": unknown_resources[:20],
                "unknown_count": len(unknown_resources),
            },
            db=db,
        )


def _log_scenario_failure(
    db: Session,
    scenario_id: int,
    run_id: int | None,
    stage: str,
    error: Exception,
):
    log_event(
        actor_role="system",
        actor_id="scenario_runner",
        event_type="SCENARIO_RUN_FAILED",
        payload={
            "scenario_id": int(scenario_id),
            "solver_run_id": (None if run_id is None else int(run_id)),
            "stage": str(stage),
            "error_type": type(error).__name__,
            "error_message": str(error),
        },
        db=db,
    )


# ============================================================
# SCENARIO SOLVER RUN
# ============================================================

def run_scenario(db: Session, scenario_id: int, scope_mode: str = "full"):
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise ValueError("Scenario not found")

    normalized_scope_mode = str(scope_mode or "full").strip().lower()
    if normalized_scope_mode not in {"full", "focused"}:
        raise ValueError("preflight_failed:invalid_scope_mode")

    stale_cutoff = datetime.utcnow() - timedelta(minutes=30)
    live_running_stale = db.query(SolverRun).filter(
        SolverRun.mode == "live",
        SolverRun.status == "running",
        SolverRun.started_at.isnot(None),
        SolverRun.started_at < stale_cutoff,
    ).all()
    if live_running_stale:
        for row in live_running_stale:
            row.status = "failed"
        db.commit()

    scenario.status = "running"
    db.commit()

    baseline_df_raw = _load_baseline_demand()
    scenario_human_df = _build_scenario_human_signal(db, scenario_id)
    scenario_scope = _extract_scenario_scope(scenario_human_df)
    selected_districts = set(scenario_scope.get("districts") or set())

    baseline_df = _filter_baseline_to_scope(baseline_df_raw, scenario_scope)

    scenario_horizon = None
    if scenario_human_df is not None and not scenario_human_df.empty and "time" in scenario_human_df.columns:
        try:
            scenario_horizon = int(max(1, min(30, int(scenario_human_df["time"].max()))))
        except Exception:
            scenario_horizon = None

    combined_human_df = _normalize_demand_frame(scenario_human_df)

    final_df, used_model_ids = _assemble_final_demand(
        db,
        baseline_df,
        combined_human_df,
        include_model_ids=True,
    )

    _assert_scope_subset(combined_human_df, selected_districts, label="scenario_human_demand")
    _assert_scope_subset(final_df, selected_districts, label="final_solver_demand")

    if scenario_horizon is not None and "time" in final_df.columns:
        final_df = final_df[final_df["time"] <= int(scenario_horizon)].copy()

    if normalized_scope_mode == "focused" and scenario_human_df is not None and not scenario_human_df.empty:
        focus_districts = set(scenario_human_df["district_code"].astype(str).unique().tolist()) if "district_code" in scenario_human_df.columns else set()
        focus_resources = set(scenario_human_df["resource_id"].astype(str).unique().tolist()) if "resource_id" in scenario_human_df.columns else set()

        before_rows = int(len(final_df.index))
        if focus_districts:
            final_df = final_df[final_df["district_code"].astype(str).isin(focus_districts)]
        if focus_resources:
            final_df = final_df[final_df["resource_id"].astype(str).isin(focus_resources)]
        final_df = final_df.copy()

        log_event(
            actor_role="system",
            actor_id="scenario_runner",
            event_type="SCENARIO_SCOPE_APPLIED",
            payload={
                "scenario_id": int(scenario_id),
                "scope_mode": "focused",
                "rows_before": before_rows,
                "rows_after": int(len(final_df.index)),
                "focus_districts": int(len(focus_districts)),
                "focus_resources": int(len(focus_resources)),
            },
            db=db,
        )

    _assert_scope_subset(final_df, selected_districts, label="final_solver_demand_post_focus")

    scenario_demand_districts = sorted(set(combined_human_df["district_code"].astype(str).unique().tolist())) if not combined_human_df.empty else []
    solver_input_districts = sorted(set(final_df["district_code"].astype(str).unique().tolist())) if not final_df.empty else []
    print("Scenario Demand Districts:", scenario_demand_districts)
    print("Scenario Demand District Count:", len(scenario_demand_districts))
    print("Solver Input District Set:", solver_input_districts)
    print("Solver Input District Count:", len(solver_input_districts))
    log_event(
        actor_role="system",
        actor_id="scenario_runner",
        event_type="SCENARIO_SCOPE_DIAGNOSTICS",
        payload={
            "scenario_id": int(scenario_id),
            "scenario_demand_districts": scenario_demand_districts,
            "scenario_demand_district_count": len(scenario_demand_districts),
            "solver_input_districts": solver_input_districts,
            "solver_input_district_count": len(solver_input_districts),
        },
        db=db,
    )

    try:
        _preflight_validate_scenario_run(
            db=db,
            scenario_id=int(scenario_id),
            baseline_df=baseline_df,
            scenario_human_df=scenario_human_df,
            final_df=final_df,
        )
    except Exception as exc:
        scenario.status = "failed"
        db.commit()
        _log_scenario_failure(db, scenario_id=int(scenario_id), run_id=None, stage="preflight", error=exc)
        db.commit()
        raise

    solver_horizon = 2
    if scenario_horizon is not None:
        solver_horizon = max(2, int(scenario_horizon))

    path = (
        CORE_ENGINE_ROOT
        / "phase4"
        / "scenarios"
        / "generated"
        / f"scenario_{scenario_id}_demand.csv"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    final_df[["district_code", "resource_id", "time", "demand"]].to_csv(path, index=False)

    state_stock_override = _build_state_stock_override_file(db, scenario_id)
    national_stock_override = _build_national_stock_override_file(db, scenario_id)

    if ENABLE_MUTUAL_AID:
        transfer_state_override = build_state_stock_with_confirmed_transfers(
            db=db,
            base_state_stock_path=PHASE4_RESOURCE_DATA / "state_resource_stock.csv",
            output_path=CORE_ENGINE_ROOT / "phase4" / "scenarios" / "generated" / f"scenario_{scenario_id}_state_stock_with_mutual_aid.csv",
        )
        if transfer_state_override:
            state_stock_override = transfer_state_override

    # -------------------------
    # Create solver run record
    # -------------------------

    run = SolverRun(
        scenario_id=scenario_id,
        mode="scenario",
        status="running",
        demand_snapshot_path=str(path),
        weight_model_id=max(used_model_ids) if used_model_ids else None,
    )

    db.add(run)
    db.commit()
    db.refresh(run)

    pu_refs = get_latest_priority_urgency_model_refs(db)
    run.priority_model_id = pu_refs.get("priority_model_id")
    run.urgency_model_id = pu_refs.get("urgency_model_id")
    db.commit()

    if used_model_ids:
        log_event(
            actor_role="system",
            actor_id="demand_learning",
            event_type="DEMAND_WEIGHT_MODEL_APPLIED",
            payload={
                "solver_run_id": int(run.id),
                "weight_model_ids": sorted(list(used_model_ids)),
                "primary_weight_model_id": run.weight_model_id,
            },
            db=db,
        )

    persist_final_demands(db, run.id, final_df)
    db.commit()

    stage = "solver_execution"
    try:
        # -------------------------
        # Run solver
        # -------------------------
        with solver_execution_lock:
            run_solver(
                demand_override_path=str(path),
                state_stock_override_path=state_stock_override,
                national_stock_override_path=national_stock_override,
                horizon_override=solver_horizon,
            )

            stage = "ingest_results"
            ingest_solver_results(db, run.id)

        alloc_district_rows = db.query(Allocation.district_code).filter(Allocation.solver_run_id == int(run.id)).distinct().all()
        alloc_districts = sorted({str(r[0]) for r in alloc_district_rows if r and r[0] is not None})
        rogue_alloc_districts = sorted([d for d in alloc_districts if d not in selected_districts])
        if rogue_alloc_districts:
            raise ValueError(
                f"post_ingest_scope_breach:districts={len(rogue_alloc_districts)}:sample={rogue_alloc_districts[:10]}"
            )

        if ENABLE_MUTUAL_AID:
            stage = "mark_transfers_consumed"
            mark_confirmed_transfers_consumed(db, solver_run_id=int(run.id))
            stage = "apply_transfer_provenance"
            apply_transfer_provenance_to_run(db, solver_run_id=int(run.id))

        stage = "capture_demand_learning"
        capture_demand_learning_events(
            db,
            solver_run_id=int(run.id),
            baseline_df=baseline_df,
            human_df=combined_human_df,
            final_df=final_df,
        )

        stage = "capture_priority_urgency"
        capture_priority_urgency_events_for_scenario(
            db,
            solver_run_id=int(run.id),
            scenario_id=int(scenario_id),
            baseline_df=baseline_df,
            final_df=final_df,
        )
        db.commit()

        stage = "write_agent_outputs"
        _write_agent_outputs(
            db,
            scenario_id=scenario_id,
            solver_run_id=run.id,
            baseline_df=baseline_df,
            human_df=combined_human_df,
            final_df=final_df,
        )

        persist_solver_run_snapshot(db, int(run.id))
        run.status = "completed"
        scenario.status = "completed"
        db.commit()

    except Exception as exc:
        run.status = "failed"
        scenario.status = "failed"
        _log_scenario_failure(db, scenario_id=int(scenario_id), run_id=int(run.id), stage=stage, error=exc)
        db.commit()
        raise
