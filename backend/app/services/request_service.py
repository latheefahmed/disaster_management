from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
import pandas as pd
import os
import time
import math
import hashlib
import traceback
import threading
import json
from datetime import datetime, timedelta
from uuid import UUID

from app.models.request import ResourceRequest
from app.models.district import District
from app.models.solver_run import SolverRun
from app.models.allocation import Allocation
from app.models.mutual_aid_request import MutualAidRequest
from app.models.resource import Resource
from app.models.request_prediction import RequestPrediction
from app.models.final_demand import FinalDemand
from app.models.mutual_aid_offer import MutualAidOffer

from app.services.audit_service import log_event
from app.services.scenario_runner import build_live_demand_snapshot
from app.services.final_demand_service import persist_final_demands
from app.services.final_demand_service import get_final_demand_slot_map
from app.services.demand_learning_service import (
    apply_weight_models_to_merged_demand,
    capture_demand_learning_events,
)
from app.services.priority_urgency_ml_service import (
    capture_priority_urgency_events,
    get_latest_priority_urgency_model_refs,
    persist_request_prediction,
    resolve_effective_rank,
)
from app.services.neural_controller import get_params as get_meta_controller_params
from app.services.stream_feature_service import build_feature_vectors
from app.services.ls_nmc_training_service import online_train_after_run

from app.engine_bridge.solver_runner import run_solver
from app.engine_bridge.ingest import ingest_solver_results
from app.engine_bridge.solver_lock import solver_execution_lock
from app.database import SessionLocal
from app.config import (
    CORE_ENGINE_ROOT,
    PHASE4_RESOURCE_DATA,
    ENABLE_MUTUAL_AID,
    ENABLE_AGENT_ENGINE,
    ENABLE_NN_META_CONTROLLER,
)
from app.services.mutual_aid_service import (
    build_state_stock_with_confirmed_transfers,
    mark_confirmed_transfers_consumed,
    apply_transfer_provenance_to_run,
    create_requests_from_unmet_allocations,
    get_candidate_states,
    create_mutual_aid_offer,
    respond_to_offer,
)
from app.services.agent_engine import run_agent_engine
from app.services.stock_refill_service import build_live_stock_override_files
from sqlalchemy import func, or_, and_, text
from app.services.resource_dictionary_service import resolve_resource_id
from app.services.canonical_resources import max_quantity_for, requires_integer_quantity, CANONICAL_RESOURCE_ORDER
from app.services.cache_service import get_or_set_cached
from app.services.perf_observability import timed_call, log_perf_event
from app.services.run_snapshot_service import persist_solver_run_snapshot


BASELINE_PATH = str(
    CORE_ENGINE_ROOT /
    "phase3/output/district_resource_demand.csv"
)

LIVE_DEMAND_PATH = str(
    CORE_ENGINE_ROOT /
    "phase4/optimization/output/live_demand.csv"
)

AUTO_ESCALATION_ENABLED = os.getenv("AUTO_ESCALATION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTO_ESCALATION_MIN_UNMET_QTY = float(os.getenv("AUTO_ESCALATION_MIN_UNMET_QTY", "1"))
AUTO_ESCALATION_IMMEDIATE_TIME_MAX = int(os.getenv("AUTO_ESCALATION_IMMEDIATE_TIME_MAX", "0"))
AUTO_ESCALATION_NATIONAL_UNMET_RATIO = float(os.getenv("AUTO_ESCALATION_NATIONAL_UNMET_RATIO", "0.40"))
AUTO_ESCALATION_NATIONAL_DELAY_MINUTES = int(os.getenv("AUTO_ESCALATION_NATIONAL_DELAY_MINUTES", "30"))
AUTO_ESCALATION_NEIGHBOR_MAX_STATES = int(os.getenv("AUTO_ESCALATION_NEIGHBOR_MAX_STATES", "3"))
AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION = float(os.getenv("AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION", "0.55"))
AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP = float(os.getenv("AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP", "0.20"))
AUTO_ESCALATION_NEIGHBOR_ACCEPT_THRESHOLD = int(os.getenv("AUTO_ESCALATION_NEIGHBOR_ACCEPT_THRESHOLD", "55"))
AUTO_ESCALATION_NEIGHBOR_EMERGENCY_ACCEPT_THRESHOLD = int(os.getenv("AUTO_ESCALATION_NEIGHBOR_EMERGENCY_ACCEPT_THRESHOLD", "75"))


def _priority_urgency_influence_mode() -> str:
    mode = str(os.getenv("PRIORITY_URGENCY_INFLUENCE_MODE", "off") or "off").strip().lower()
    if mode in {"off", "shadow", "active"}:
        return mode
    return "off"


def _resolve_rank_for_decision(human_value, predicted_value, default: int = 1) -> tuple[int, str]:
    if human_value is not None:
        return resolve_effective_rank(human_value, None, default=default), "human"

    mode = _priority_urgency_influence_mode()
    if mode == "active" and predicted_value is not None:
        return resolve_effective_rank(None, predicted_value, default=default), "predicted"

    return resolve_effective_rank(None, None, default=default), "default"


def _normalize_demand_mode(mode: str | None) -> str:
    raw = str(mode or "").strip().lower()
    mapping = {
        "ai_human": "baseline_plus_human",
        "baseline_plus_human": "baseline_plus_human",
        "human_only": "human_only",
        "only_human": "human_only",
        "ai_only": "baseline_only",
        "baseline_only": "baseline_only",
    }
    if raw not in mapping:
        raise ValueError("Invalid demand mode")
    return mapping[raw]


def _is_uuid_like(value: str) -> bool:
    try:
        UUID(value)
        return True
    except Exception:
        return False


def _normalize_resource_id(db: Session, resource_id, strict: bool = True) -> str:
    return resolve_resource_id(db, resource_id, strict=strict)


def _lifecycle_for_status(status: str | None) -> str:
    mapping = {
        "pending": "CREATED",
        "solving": "SENT_TO_SOLVER",
        "allocated": "ALLOCATED",
        "partial": "PARTIAL",
        "unmet": "UNMET",
        "escalated_state": "ESCALATED",
        "escalated_national": "ESCALATED",
        "failed": "FAILED",
    }
    return mapping.get(str(status or "").lower(), "CREATED")


def _is_sqlite_locked_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "database is locked" in msg or "database table is locked" in msg


def _commit_with_retry(db: Session, attempts: int = 5, delay_sec: float = 0.2):
    last_err: Exception | None = None
    for idx in range(max(1, int(attempts))):
        try:
            db.commit()
            return
        except OperationalError as err:
            db.rollback()
            last_err = err
            if not _is_sqlite_locked_error(err) or idx == attempts - 1:
                raise
            time.sleep(delay_sec * (idx + 1))
    if last_err is not None:
        raise last_err


def _stable_acceptance_score(request_id: int, offering_state: str) -> int:
    token = f"{int(request_id)}:{str(offering_state)}".encode("utf-8")
    digest = hashlib.sha256(token).hexdigest()[:8]
    return int(digest, 16) % 100


def _state_resource_stock(
    db: Session,
    state_code: str,
    resource_id: str,
    cache: dict[tuple[str, str], float],
) -> float:
    key = (str(state_code), str(resource_id))
    if key in cache:
        return float(cache[key])

    from app.services.kpi_service import get_state_stock_rows

    value = 0.0
    try:
        rows = get_state_stock_rows(db, str(state_code))
        for row in rows:
            if str(row.get("resource_id") or "") == str(resource_id):
                value = max(0.0, float(row.get("state_stock") or 0.0))
                break
    except Exception:
        value = 0.0

    cache[key] = float(value)
    return float(value)


def _seed_neighbor_offers_for_request(
    db: Session,
    req: ResourceRequest,
    aid_request: MutualAidRequest,
    unmet_qty: float,
    emergency_mode: bool,
    stock_cache: dict[tuple[str, str], float],
) -> dict[str, float]:
    accepted_existing = float(
        db.query(func.coalesce(func.sum(MutualAidOffer.quantity_offered), 0.0)).filter(
            MutualAidOffer.request_id == int(aid_request.id),
            MutualAidOffer.status == "accepted",
        ).scalar()
        or 0.0
    )
    remaining = max(0.0, float(unmet_qty) - accepted_existing)
    if remaining <= 1e-9:
        return {"offers_created": 0.0, "offers_accepted": 0.0, "accepted_quantity": 0.0}

    neighbors = get_candidate_states(
        db,
        requesting_state=str(req.state_code),
        limit=max(1, int(AUTO_ESCALATION_NEIGHBOR_MAX_STATES) * 2),
    )
    if not neighbors:
        return {"offers_created": 0.0, "offers_accepted": 0.0, "accepted_quantity": 0.0}

    max_states = max(1, int(AUTO_ESCALATION_NEIGHBOR_MAX_STATES))
    offer_fraction = max(0.05, min(1.0, float(AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION)))
    stock_cap = max(0.05, min(1.0, float(AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP)))
    accept_threshold = int(AUTO_ESCALATION_NEIGHBOR_EMERGENCY_ACCEPT_THRESHOLD if emergency_mode else AUTO_ESCALATION_NEIGHBOR_ACCEPT_THRESHOLD)

    offers_created = 0
    offers_accepted = 0
    accepted_quantity = 0.0

    for item in neighbors:
        if offers_created >= max_states or remaining <= 1e-9:
            break

        offering_state = str(item.get("state_code") or "").strip()
        if not offering_state or offering_state == str(req.state_code):
            continue

        existing = db.query(MutualAidOffer).filter(
            MutualAidOffer.request_id == int(aid_request.id),
            MutualAidOffer.offering_state == str(offering_state),
            MutualAidOffer.status.in_(["pending", "accepted"]),
        ).first()
        if existing is not None:
            continue

        available = _state_resource_stock(db, offering_state, str(req.resource_id), stock_cache)
        if available <= 1e-9:
            continue

        cap_qty = max(0.0, available * stock_cap)
        proposed_qty = min(
            remaining,
            cap_qty,
            max(float(AUTO_ESCALATION_MIN_UNMET_QTY), remaining * offer_fraction),
        )
        if proposed_qty <= 1e-9:
            continue

        try:
            offer = create_mutual_aid_offer(
                db=db,
                request_id=int(aid_request.id),
                offering_state=offering_state,
                quantity_offered=float(proposed_qty),
                cap_quantity=float(cap_qty),
            )
            offers_created += 1

            score = _stable_acceptance_score(int(req.id), offering_state)
            decision = "accepted" if score < accept_threshold else "rejected"
            responded = respond_to_offer(
                db=db,
                offer_id=int(offer.id),
                decision=decision,
                actor_state=str(req.state_code),
            )
            if str(responded.status or "").lower() == "accepted":
                offers_accepted += 1
                qty = max(0.0, float(offer.quantity_offered or 0.0))
                accepted_quantity += qty
                remaining = max(0.0, remaining - qty)
        except Exception:
            db.rollback()
            continue

    return {
        "offers_created": float(offers_created),
        "offers_accepted": float(offers_accepted),
        "accepted_quantity": float(accepted_quantity),
    }


def _auto_progress_escalation_chain(db: Session, solver_run_id: int) -> dict[str, int]:
    if not AUTO_ESCALATION_ENABLED:
        return {
            "state_marked": 0,
            "mutual_aid_created": 0,
            "national_marked": 0,
        }

    rows = db.query(ResourceRequest).filter(
        ResourceRequest.run_id == int(solver_run_id),
        ResourceRequest.status.in_(["partial", "unmet", "escalated_state", "escalated_national"]),
    ).all()

    if not rows:
        return {
            "state_marked": 0,
            "mutual_aid_created": 0,
            "national_marked": 0,
        }

    now = datetime.utcnow()
    state_marked = 0
    mutual_aid_created = 0
    national_marked = 0
    neighbor_offers_created = 0
    neighbor_offers_accepted = 0
    neighbor_accepted_qty = 0.0
    stock_cache: dict[tuple[str, str], float] = {}

    pred_map: dict[int, RequestPrediction] = {}
    if _priority_urgency_influence_mode() == "active":
        request_ids = [int(r.id) for r in rows]
        if request_ids:
            pred_rows = db.query(RequestPrediction).filter(
                RequestPrediction.request_id.in_(request_ids)
            ).order_by(RequestPrediction.created_at.desc(), RequestPrediction.id.desc()).all()
            for row in pred_rows:
                rid = int(row.request_id)
                if rid not in pred_map:
                    pred_map[rid] = row

    for req in rows:
        requested_qty = max(0.0, float(req.quantity or 0.0))
        unmet_qty = max(
            0.0,
            float(req.unmet_quantity or 0.0),
            requested_qty - float(req.allocated_quantity or 0.0),
        )
        if unmet_qty < AUTO_ESCALATION_MIN_UNMET_QTY:
            continue

        unmet_ratio = (unmet_qty / requested_qty) if requested_qty > 1e-9 else 1.0

        open_aid = db.query(MutualAidRequest).filter(
            MutualAidRequest.requesting_state == str(req.state_code),
            MutualAidRequest.requesting_district == str(req.district_code),
            MutualAidRequest.resource_id == str(req.resource_id),
            MutualAidRequest.time == int(req.time),
            MutualAidRequest.status.in_(["open", "partially_filled"]),
        ).order_by(MutualAidRequest.created_at.desc()).first()

        if req.status != "escalated_national":
            if req.status != "escalated_state":
                req.status = "escalated_state"
                req.lifecycle_state = "ESCALATED"
                req.unmet_quantity = float(unmet_qty)
                state_marked += 1

            if open_aid is None:
                open_aid = MutualAidRequest(
                    requesting_state=str(req.state_code),
                    requesting_district=str(req.district_code),
                    resource_id=str(req.resource_id),
                    quantity_requested=float(unmet_qty),
                    time=int(req.time),
                    status="open",
                )
                db.add(open_aid)
                db.flush()
                mutual_aid_created += 1

        aid_age_minutes = 0.0
        if open_aid is not None and getattr(open_aid, "created_at", None) is not None:
            aid_age_minutes = max(0.0, (now - open_aid.created_at).total_seconds() / 60.0)

        pred = pred_map.get(int(req.id))
        predicted_priority = None if pred is None else pred.predicted_priority
        predicted_urgency = None if pred is None else pred.predicted_urgency
        effective_priority, _ = _resolve_rank_for_decision(req.priority, predicted_priority, default=1)
        effective_urgency, _ = _resolve_rank_for_decision(req.urgency, predicted_urgency, default=1)

        immediate_and_severe = int(req.time or 0) <= AUTO_ESCALATION_IMMEDIATE_TIME_MAX and unmet_ratio >= AUTO_ESCALATION_NATIONAL_UNMET_RATIO
        immediate_high_priority = int(req.time or 0) <= AUTO_ESCALATION_IMMEDIATE_TIME_MAX and (
            int(effective_priority or 0) >= 5 or int(effective_urgency or 0) >= 5
        ) and unmet_qty >= AUTO_ESCALATION_MIN_UNMET_QTY
        delayed_without_fill = open_aid is not None and aid_age_minutes >= float(AUTO_ESCALATION_NATIONAL_DELAY_MINUTES)

        emergency_pressure = (
            unmet_ratio >= max(float(AUTO_ESCALATION_NATIONAL_UNMET_RATIO), 0.60)
            and (int(effective_priority or 0) >= 4 or int(effective_urgency or 0) >= 4)
        )

        if open_aid is not None and (emergency_pressure or delayed_without_fill or unmet_ratio >= float(AUTO_ESCALATION_NATIONAL_UNMET_RATIO)):
            seeded = _seed_neighbor_offers_for_request(
                db=db,
                req=req,
                aid_request=open_aid,
                unmet_qty=float(unmet_qty),
                emergency_mode=bool(emergency_pressure),
                stock_cache=stock_cache,
            )
            neighbor_offers_created += int(seeded.get("offers_created", 0.0))
            neighbor_offers_accepted += int(seeded.get("offers_accepted", 0.0))
            neighbor_accepted_qty += float(seeded.get("accepted_quantity", 0.0))

        if req.status != "escalated_national" and (immediate_and_severe or immediate_high_priority or delayed_without_fill or emergency_pressure):
            req.status = "escalated_national"
            req.lifecycle_state = "ESCALATED"
            req.unmet_quantity = float(unmet_qty)
            national_marked += 1

    _commit_with_retry(db)

    if state_marked > 0:
        log_event(
            actor_role="system",
            actor_id="auto_escalation_orchestrator",
            event_type="AUTO_ESCALATED_TO_STATE_MARKET",
            payload={
                "solver_run_id": int(solver_run_id),
                "requests_marked": int(state_marked),
                "mutual_aid_requests_created": int(mutual_aid_created),
            },
            db=db,
        )

    if national_marked > 0:
        log_event(
            actor_role="system",
            actor_id="auto_escalation_orchestrator",
            event_type="AUTO_ESCALATED_TO_NATIONAL",
            payload={
                "solver_run_id": int(solver_run_id),
                "requests_marked": int(national_marked),
                "policy": {
                    "immediate_time_max": int(AUTO_ESCALATION_IMMEDIATE_TIME_MAX),
                    "national_unmet_ratio": float(AUTO_ESCALATION_NATIONAL_UNMET_RATIO),
                    "delay_minutes": int(AUTO_ESCALATION_NATIONAL_DELAY_MINUTES),
                },
            },
            db=db,
        )

    if neighbor_offers_created > 0:
        log_event(
            actor_role="system",
            actor_id="auto_escalation_orchestrator",
            event_type="AUTO_NEIGHBOR_OFFERS_SEEDED",
            payload={
                "solver_run_id": int(solver_run_id),
                "offers_created": int(neighbor_offers_created),
                "offers_accepted": int(neighbor_offers_accepted),
                "accepted_quantity": float(neighbor_accepted_qty),
                "policy": {
                    "max_neighbor_states": int(AUTO_ESCALATION_NEIGHBOR_MAX_STATES),
                    "offer_fraction": float(AUTO_ESCALATION_NEIGHBOR_OFFER_FRACTION),
                    "stock_cap": float(AUTO_ESCALATION_NEIGHBOR_STOCK_UTILIZATION_CAP),
                    "accept_threshold": int(AUTO_ESCALATION_NEIGHBOR_ACCEPT_THRESHOLD),
                    "emergency_accept_threshold": int(AUTO_ESCALATION_NEIGHBOR_EMERGENCY_ACCEPT_THRESHOLD),
                },
            },
            db=db,
        )

    return {
        "state_marked": int(state_marked),
        "mutual_aid_created": int(mutual_aid_created),
        "national_marked": int(national_marked),
    }


def _coerce_rank(value) -> int | None:
    if value is None:
        return None
    numeric = int(value)
    if numeric < 1:
        return 1
    if numeric > 5:
        return 5
    return numeric


def _normalize_request_time(_value) -> int:
    try:
        normalized = int(_value)
    except (TypeError, ValueError):
        raise ValueError("time must be an integer")

    if normalized < 0:
        raise ValueError("time must be >= 0")
    return normalized


def _normalize_quantity(resource_id: str, quantity_value) -> float:
    try:
        quantity = float(quantity_value)
    except (TypeError, ValueError):
        raise ValueError("quantity must be a number")

    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("quantity must be greater than 0")

    rid = str(resource_id or "").strip()
    if requires_integer_quantity(rid) and not float(quantity).is_integer():
        raise ValueError(f"quantity for resource '{rid}' must be a whole number")

    max_qty = float(max_quantity_for(rid))
    if quantity > max_qty:
        raise ValueError(f"quantity exceeds max allowed for resource '{rid}' ({max_qty:.0f})")

    return float(quantity)


def _normalize_confidence(value) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise ValueError("confidence must be a number")

    if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def _normalize_source(value) -> str:
    source = str(value or "human").strip()
    if not source:
        raise ValueError("source is required")
    if len(source) > 64:
        raise ValueError("source is too long")
    return source


def _aggregate_slot_demands(df: pd.DataFrame, demand_col: str = "demand") -> pd.DataFrame:
    if df is None or df.empty:
        return df

    work = df.copy()
    required = {"district_code", "resource_id", "time", demand_col}
    if not required.issubset(set(work.columns)):
        return work

    work["district_code"] = work["district_code"].astype(str)
    work["resource_id"] = work["resource_id"].astype(str)
    work["time"] = work["time"].astype(int)
    work[demand_col] = work[demand_col].astype(float)

    grouped = work.groupby(["district_code", "resource_id", "time"], as_index=False)[demand_col].sum()

    if "demand_mode" in work.columns:
        grouped = grouped.merge(
            work[["district_code", "resource_id", "time", "demand_mode"]].drop_duplicates(
                subset=["district_code", "resource_id", "time"], keep="last"
            ),
            on=["district_code", "resource_id", "time"],
            how="left",
        )
    if "source_mix" in work.columns:
        grouped = grouped.merge(
            work[["district_code", "resource_id", "time", "source_mix"]].drop_duplicates(
                subset=["district_code", "resource_id", "time"], keep="last"
            ),
            on=["district_code", "resource_id", "time"],
            how="left",
        )

    return grouped


def _expand_month_horizon(final_df: pd.DataFrame, district_codes: list[str]) -> pd.DataFrame:
    if final_df is None:
        final_df = pd.DataFrame(columns=["district_code", "resource_id", "time", "demand", "demand_mode", "source_mix"])

    work = final_df.copy()
    if work.empty:
        work = pd.DataFrame(columns=["district_code", "resource_id", "time", "demand", "demand_mode", "source_mix"])

    required_cols = {"district_code", "resource_id", "time", "demand"}
    missing = required_cols - set(work.columns)
    if missing:
        raise ValueError(f"Final demand frame missing required columns: {sorted(missing)}")

    work["district_code"] = work["district_code"].astype(str)
    work["resource_id"] = work["resource_id"].astype(str)
    work["time"] = work["time"].astype(int)
    work["demand"] = work["demand"].astype(float)
    work = _aggregate_slot_demands(work, demand_col="demand")

    times = list(range(30))
    districts = sorted({str(d) for d in district_codes if str(d).strip()})
    if not districts:
        districts = sorted(work["district_code"].astype(str).unique().tolist())
    resources = [rid for rid in CANONICAL_RESOURCE_ORDER]

    grid = pd.MultiIndex.from_product(
        [districts, resources, times],
        names=["district_code", "resource_id", "time"],
    ).to_frame(index=False)

    merged = grid.merge(
        work,
        on=["district_code", "resource_id", "time"],
        how="left",
    )

    merged["demand"] = merged["demand"].fillna(0.0).astype(float)
    merged["demand_mode"] = merged.get("demand_mode", "baseline_plus_human")
    merged["demand_mode"] = merged["demand_mode"].fillna("baseline_plus_human")
    merged["source_mix"] = merged.get("source_mix", "expanded_month_horizon")
    merged["source_mix"] = merged["source_mix"].fillna("expanded_month_horizon")

    return merged[["district_code", "resource_id", "time", "demand", "demand_mode", "source_mix"]]


def _integerize_demand_frame(final_df: pd.DataFrame) -> pd.DataFrame:
    if final_df is None or final_df.empty:
        return final_df

    work = final_df.copy()
    work["demand"] = work["demand"].astype(float).fillna(0.0)
    work["demand"] = work["demand"].map(lambda v: float(math.ceil(v)) if float(v) > 0.0 else 0.0)

    return work


def to_ui_demand_mode(mode: str | None) -> str:
    canonical = _normalize_demand_mode(mode)
    if canonical == "baseline_plus_human":
        return "ai_human"
    if canonical == "human_only":
        return "human_only"
    return "ai_only"


# ---------------------------
# Demand Mode
# ---------------------------

def get_district_demand_mode(db: Session, district_code: str) -> str:
    d = db.query(District)\
        .filter(District.district_code == district_code)\
        .first()

    return _normalize_demand_mode(d.demand_mode if d else "baseline_plus_human")


def set_district_demand_mode(
    db: Session,
    district_code: str,
    demand_mode: str
):
    d = db.query(District)\
        .filter(District.district_code == district_code)\
        .first()

    if not d:
        raise ValueError("District not found")

    d.demand_mode = _normalize_demand_mode(demand_mode)
    db.commit()
    db.refresh(d)

    return {
        "district_code": district_code,
        "demand_mode": d.demand_mode
    }


# ---------------------------
# Merge
# ---------------------------

def merge_baseline_and_human(db: Session, base_df, human_df, solver_run_id: int | None = None):
    base_df = base_df.copy()
    human_df = human_df.copy()

    if not base_df.empty:
        base_df["district_code"] = base_df["district_code"].astype(str)
        base_df["resource_id"] = base_df["resource_id"].astype(str)
        base_df["time"] = base_df["time"].astype(int)
        base_df = _aggregate_slot_demands(base_df, demand_col="demand")

    if not human_df.empty:
        human_df["district_code"] = human_df["district_code"].astype(str)
        human_df["resource_id"] = human_df["resource_id"].astype(str)
        human_df["time"] = human_df["time"].astype(int)
        human_df = _aggregate_slot_demands(human_df, demand_col="demand")

    merged = base_df.merge(
        human_df,
        on=["district_code", "resource_id", "time"],
        how="outer",
        suffixes=("_base", "_human")
    )

    merged["demand_mode"] = "baseline_plus_human"
    merged["source_mix"] = "merged"

    weighted, model_ids = apply_weight_models_to_merged_demand(
        db,
        merged.rename(columns={
            "demand_base": "demand_baseline",
            "demand_human": "demand_human",
        })
    )

    context = {
        "unmet_ratio": 0.0,
        "delay_ratio": 0.0,
    }

    if ENABLE_NN_META_CONTROLLER:
        try:
            feature_df = build_feature_vectors(
                db=db,
                base_df=base_df.rename(columns={"demand": "demand"}),
                human_df=human_df.rename(columns={"demand": "demand"}),
                solver_run_id=solver_run_id,
            )
            if feature_df is not None and not feature_df.empty:
                context["unmet_ratio"] = float(feature_df["unmet_ratio_last_run"].mean())
                context["delay_ratio"] = min(1.0, max(0.0, float(feature_df["avg_delay_last_5"].mean()) / 24.0))
        except Exception as err:
            print("Feature vector build failed, continuing deterministic merge:", err)

        try:
            _meta_params = get_meta_controller_params(db, solver_run_id=solver_run_id, context=context)
        except Exception as err:
            print("Meta-controller hook failed, continuing deterministic merge:", err)

    out = weighted.rename(columns={
        "demand_baseline": "demand_base",
    })

    if "demand" not in out.columns:
        demand_base = out["demand_base"] if "demand_base" in out.columns else 0.0
        demand_human = out["demand_human"] if "demand_human" in out.columns else 0.0
        out["demand"] = demand_base + demand_human

    return out[["district_code", "resource_id", "time", "demand"]], model_ids


# ---------------------------
# Background Solver
# ---------------------------

def _run_solver_job(run_id: int):

    db = SessionLocal()

    try:
        solver_run = db.query(SolverRun)\
            .filter(SolverRun.id == run_id)\
            .first()

        candidate_statuses = ["pending", "escalated_national", "escalated_state"]
        raw_pending_rows = db.query(ResourceRequest)
        raw_pending_rows = raw_pending_rows.filter(
            ResourceRequest.status.in_(candidate_statuses),
            ResourceRequest.run_id == 0,
        ).all()

        pending_ids: list[int] = []
        for req in raw_pending_rows:
            try:
                normalized_resource = _normalize_resource_id(db, req.resource_id, strict=True)
                normalized_time = _normalize_request_time(req.time)
                normalized_qty = _normalize_quantity(str(normalized_resource), req.quantity)
                req.resource_id = str(normalized_resource)
                req.time = int(normalized_time)
                req.quantity = float(normalized_qty)
                pending_ids.append(int(req.id))
            except Exception:
                req.status = "failed"
                req.lifecycle_state = "UNMET"
                req.included_in_run = 0
                req.queued = 0
                req.run_id = 0

        pending_requests: list[ResourceRequest] = []
        if pending_ids:
            pending_requests = db.query(ResourceRequest).filter(ResourceRequest.id.in_(pending_ids)).order_by(ResourceRequest.id.asc()).all()

            slot_keeper: dict[tuple[str, str, int], ResourceRequest] = {}
            duplicate_ids: list[int] = []
            for req in pending_requests:
                slot_key = (str(req.district_code), str(req.resource_id), int(req.time))
                keeper = slot_keeper.get(slot_key)
                if keeper is None:
                    slot_keeper[slot_key] = req
                    continue
                keeper.quantity = float(keeper.quantity or 0.0) + float(req.quantity or 0.0)
                if req.priority is not None:
                    keeper.priority = req.priority
                if req.urgency is not None:
                    keeper.urgency = req.urgency
                keeper.confidence = float(req.confidence or keeper.confidence or 1.0)
                keeper.source = str(req.source or keeper.source or "human")
                duplicate_ids.append(int(req.id))

            if duplicate_ids:
                db.query(RequestPrediction).filter(RequestPrediction.request_id.in_(duplicate_ids)).delete(synchronize_session=False)
                db.query(ResourceRequest).filter(ResourceRequest.id.in_(duplicate_ids)).delete(synchronize_session=False)
                _commit_with_retry(db)
                pending_requests = list(slot_keeper.values())
                pending_ids = [int(r.id) for r in pending_requests]
            pred_rows = db.query(RequestPrediction).filter(RequestPrediction.request_id.in_(pending_ids)).order_by(RequestPrediction.created_at.desc(), RequestPrediction.id.desc()).all()
            pred_map: dict[int, RequestPrediction] = {}
            for row in pred_rows:
                rid = int(row.request_id)
                if rid not in pred_map:
                    pred_map[rid] = row

            priority_human = 0
            priority_pred = 0
            priority_default = 0
            urgency_human = 0
            urgency_pred = 0
            urgency_default = 0

            for req in pending_requests:
                pred = pred_map.get(int(req.id))
                pp = None if pred is None else pred.predicted_priority
                pu = None if pred is None else pred.predicted_urgency

                _, p_source = _resolve_rank_for_decision(req.priority, pp, default=1)
                _, u_source = _resolve_rank_for_decision(req.urgency, pu, default=1)

                if p_source == "human":
                    priority_human += 1
                elif p_source == "predicted":
                    priority_pred += 1
                else:
                    priority_default += 1

                if u_source == "human":
                    urgency_human += 1
                elif u_source == "predicted":
                    urgency_pred += 1
                else:
                    urgency_default += 1

            log_event(
                actor_role="system",
                actor_id="priority_urgency_ml",
                event_type="EFFECTIVE_PRIORITY_URGENCY_SOURCE",
                payload={
                    "solver_run_id": int(run_id),
                    "mode": _priority_urgency_influence_mode(),
                    "priority": {
                        "human": priority_human,
                        "predicted": priority_pred,
                        "default": priority_default,
                    },
                    "urgency": {
                        "human": urgency_human,
                        "predicted": urgency_pred,
                        "default": urgency_default,
                    },
                },
                db=db,
            )

        if not pending_ids:
            persist_solver_run_snapshot(db, int(solver_run.id))
            solver_run.status = "completed"
            _commit_with_retry(db)
            _refresh_request_statuses_for_latest_live_run(db)
            _commit_with_retry(db)
            return

        human_df = build_live_demand_snapshot(db)

        if pending_ids:
            db.query(ResourceRequest)\
                .filter(ResourceRequest.id.in_(pending_ids))\
                .update({
                    "status": "solving",
                    "lifecycle_state": "SENT_TO_SOLVER",
                    "included_in_run": 1,
                    "queued": 0,
                    "run_id": int(solver_run.id),
                }, synchronize_session=False)
            _commit_with_retry(db)

        impacted_district_codes = sorted({str(r.district_code) for r in pending_requests if str(r.district_code or "").strip()})
        if impacted_district_codes:
            districts = db.query(District).filter(District.district_code.in_(impacted_district_codes)).all()
        else:
            districts = db.query(District).all()
        baseline_df = pd.read_csv(BASELINE_PATH)
        baseline_df["district_code"] = baseline_df["district_code"].astype(str)
        baseline_df["resource_id"] = baseline_df["resource_id"].astype(str)
        baseline_df["time"] = baseline_df["time"].astype(int)
        baseline_df["demand"] = baseline_df["demand"].astype(float)

        frames = []
        used_model_ids: set[int] = set()

        for d in districts:
            h = human_df[
                human_df["district_code"] == str(d.district_code)
            ]

            b = baseline_df[
                baseline_df["district_code"] == str(d.district_code)
            ]

            if d.demand_mode == "human_only":
                part = h.copy()
                part["demand_mode"] = "human_only"
                part["source_mix"] = "human"
                frames.append(part)
            elif d.demand_mode == "baseline_only":
                part = b.copy()
                part["demand_mode"] = "baseline_only"
                part["source_mix"] = "baseline"
                frames.append(part)
            else:
                part, model_ids = merge_baseline_and_human(db, b, h, solver_run_id=int(solver_run.id))
                used_model_ids.update(model_ids)
                part["demand_mode"] = "baseline_plus_human"
                part["source_mix"] = "learned_weighted" if model_ids else "merged"
                frames.append(part)

        if frames:
            final_df = pd.concat(frames, ignore_index=True)
        else:
            final_df = pd.DataFrame(columns=["district_code", "resource_id", "time", "demand", "demand_mode", "source_mix"])

        if "demand" not in final_df.columns:
            demand_base = final_df["demand_base"] if "demand_base" in final_df.columns else 0.0
            demand_human = final_df["demand_human"] if "demand_human" in final_df.columns else 0.0
            final_df["demand"] = demand_base + demand_human

        final_df["district_code"] = final_df["district_code"].astype(str)
        final_df["resource_id"] = final_df["resource_id"].astype(str)
        final_df["time"] = final_df["time"].astype(int)
        final_df["demand"] = final_df["demand"].astype(float)

        active_district_codes = [str(d.district_code) for d in districts]
        final_df = _expand_month_horizon(final_df, district_codes=active_district_codes)
        final_df = _integerize_demand_frame(final_df)

        final_count = int(len(final_df.index))
        distinct_resources = int(final_df["resource_id"].nunique()) if final_count > 0 else 0
        min_demand = float(final_df["demand"].min()) if final_count > 0 else 0.0
        max_demand = float(final_df["demand"].max()) if final_count > 0 else 0.0

        print("FINAL_DEMAND_INPUT_SUMMARY", {
            "solver_run_id": int(solver_run.id),
            "rows": final_count,
            "distinct_resource_ids": distinct_resources,
            "min_quantity": min_demand,
            "max_quantity": max_demand,
        })

        if final_count <= 0:
            raise ValueError("Abort run: final_demands.count == 0")

        solver_run.weight_model_id = max(used_model_ids) if used_model_ids else None

        pu_refs = get_latest_priority_urgency_model_refs(db)
        solver_run.priority_model_id = pu_refs.get("priority_model_id")
        solver_run.urgency_model_id = pu_refs.get("urgency_model_id")
        _commit_with_retry(db)

        if used_model_ids:
            log_event(
                actor_role="system",
                actor_id="demand_learning",
                event_type="DEMAND_WEIGHT_MODEL_APPLIED",
                payload={
                    "solver_run_id": int(solver_run.id),
                    "weight_model_ids": sorted(list(used_model_ids)),
                    "primary_weight_model_id": solver_run.weight_model_id,
                },
                db=db,
            )

        persist_final_demands(db, solver_run.id, final_df)
        _commit_with_retry(db)

        if pending_ids:
            slot_map = get_final_demand_slot_map(db, int(solver_run.id))
            invalid_requests = []
            for req in db.query(ResourceRequest).filter(ResourceRequest.id.in_(pending_ids)).all():
                key = (str(req.district_code), str(req.resource_id), int(req.time))
                if float(slot_map.get(key, 0.0)) <= 0.0:
                    invalid_requests.append(int(req.id))
            if invalid_requests:
                db.query(ResourceRequest).filter(ResourceRequest.id.in_(invalid_requests)).update(
                    {
                        "status": "failed",
                        "lifecycle_state": "UNMET",
                        "included_in_run": 0,
                        "queued": 0,
                        "run_id": 0,
                    },
                    synchronize_session=False,
                )
                _commit_with_retry(db)
                pending_ids = [rid for rid in pending_ids if int(rid) not in set(invalid_requests)]
                print("Quarantined zero-final-demand requests:", invalid_requests)

        os.makedirs(os.path.dirname(LIVE_DEMAND_PATH), exist_ok=True)
        final_df[["district_code", "resource_id", "time", "demand"]].to_csv(LIVE_DEMAND_PATH, index=False)

        state_stock_override = None
        if ENABLE_MUTUAL_AID:
            state_stock_override = build_state_stock_with_confirmed_transfers(
                db=db,
                base_state_stock_path=PHASE4_RESOURCE_DATA / "state_resource_stock.csv",
                output_path=CORE_ENGINE_ROOT / "phase4" / "scenarios" / "generated" / "live_state_stock_with_mutual_aid.csv",
            )

        district_stock_override, state_refill_override, national_stock_override = build_live_stock_override_files(
            db=db,
            state_base_path=state_stock_override,
        )
        effective_state_stock_override = state_refill_override or state_stock_override

        with solver_execution_lock:
            run_solver(
                demand_override_path=LIVE_DEMAND_PATH,
                district_stock_override_path=district_stock_override,
                state_stock_override_path=effective_state_stock_override,
                national_stock_override_path=national_stock_override,
            )
            ingest_solver_results(db, solver_run.id)

        if ENABLE_MUTUAL_AID:
            mark_confirmed_transfers_consumed(db, solver_run_id=int(solver_run.id))
            apply_transfer_provenance_to_run(db, solver_run_id=int(solver_run.id))

        if ENABLE_AGENT_ENGINE:
            try:
                run_agent_engine(
                    db,
                    trigger="solver_run",
                    context={"solver_run_id": int(solver_run.id)},
                )
            except Exception as err:
                print("Agent engine failed after solver run:", err)

        capture_demand_learning_events(
            db,
            solver_run_id=int(solver_run.id),
            baseline_df=baseline_df,
            human_df=human_df,
            final_df=final_df,
            request_ids=pending_ids,
        )

        capture_priority_urgency_events(
            db,
            solver_run_id=int(solver_run.id),
            baseline_df=baseline_df,
            final_df=final_df,
            request_ids=pending_ids,
        )
        _commit_with_retry(db)

        persist_solver_run_snapshot(db, int(solver_run.id))
        solver_run.status = "completed"
        _commit_with_retry(db)

        try:
            online_train_after_run(db, solver_run_id=int(solver_run.id))
        except Exception as err:
            print("Online LS-NMC training failed, continuing:", err)

        _refresh_request_statuses_for_latest_live_run(db)

        if ENABLE_MUTUAL_AID:
            create_requests_from_unmet_allocations(db, solver_run_id=int(solver_run.id))
            _auto_progress_escalation_chain(db, solver_run_id=int(solver_run.id))

        if ENABLE_AGENT_ENGINE:
            try:
                run_agent_engine(
                    db,
                    trigger="unmet_ingest",
                    context={"solver_run_id": int(solver_run.id)},
                )
            except Exception as err:
                print("Agent engine failed after unmet ingestion:", err)

        _commit_with_retry(db)

    except Exception as e:
        db.rollback()
        solver_run = db.query(SolverRun).filter(SolverRun.id == run_id).first()
        if solver_run is not None:
            solver_run.status = "failed"
            try:
                _commit_with_retry(db)
            except Exception:
                db.rollback()

        if 'pending_ids' in locals() and pending_ids:
            db.query(ResourceRequest)\
                .filter(ResourceRequest.id.in_(pending_ids))\
                .update({"status": "pending", "lifecycle_state": "CREATED", "included_in_run": 0, "queued": 1, "run_id": 0}, synchronize_session=False)
            try:
                _commit_with_retry(db)
            except Exception:
                db.rollback()

        print("Solver job failed:", e)
        print(traceback.format_exc())

    finally:
        db.close()


# ---------------------------
# Create Request
# ---------------------------

def create_request(db: Session, user: dict, data):
    normalized_resource_id = _normalize_resource_id(db, data.resource_id, strict=True)
    normalized_time = _normalize_request_time(data.time)
    normalized_quantity = _normalize_quantity(normalized_resource_id, data.quantity)
    normalized_confidence = _normalize_confidence(data.confidence)
    normalized_source = _normalize_source(data.source)

    existing = db.query(ResourceRequest).filter(
        ResourceRequest.district_code == user["district_code"],
        ResourceRequest.resource_id == normalized_resource_id,
        ResourceRequest.time == normalized_time,
        ResourceRequest.run_id == 0,
        ResourceRequest.status == "pending",
    ).order_by(ResourceRequest.id.desc()).first()

    if existing is not None:
        existing.quantity = float(existing.quantity or 0.0) + float(normalized_quantity)
        if _coerce_rank(data.priority) is not None:
            existing.priority = _coerce_rank(data.priority)
        if _coerce_rank(data.urgency) is not None:
            existing.urgency = _coerce_rank(data.urgency)
        existing.confidence = normalized_confidence
        existing.source = normalized_source
        existing.queued = 1
        existing.included_in_run = 0
        existing.lifecycle_state = "CREATED"
        prediction = persist_request_prediction(db, existing)
        _commit_with_retry(db)
        db.refresh(existing)
        req = existing
    else:
        req = ResourceRequest(
            district_code=user["district_code"],
            state_code=user["state_code"],
            resource_id=normalized_resource_id,
            time=normalized_time,
            quantity=normalized_quantity,
            priority=_coerce_rank(data.priority),
            urgency=_coerce_rank(data.urgency),
            confidence=normalized_confidence,
            source=normalized_source,
            status="pending",
            lifecycle_state="CREATED",
            included_in_run=0,
            queued=1,
            run_id=0,
        )

        db.add(req)
        db.flush()
        prediction = persist_request_prediction(db, req)
        _commit_with_retry(db)
        db.refresh(req)

    log_event(
        actor_role="district",
        actor_id=user["district_code"],
        event_type="REQUEST_CREATED",
        payload={
            "resource": data.resource_id,
            "resource_normalized": normalized_resource_id,
            "quantity": normalized_quantity,
            "time": normalized_time,
            "human_priority": req.priority,
            "human_urgency": req.urgency,
            "predicted_priority": None if prediction is None else prediction.predicted_priority,
            "predicted_urgency": None if prediction is None else prediction.predicted_urgency,
            "prediction_model_id": None if prediction is None else prediction.model_id,
            "prediction_confidence": None if prediction is None else prediction.confidence,
        },
        db=db,
    )

    solver_run_id = _start_live_solver_run(db)

    return {
        "status": "accepted",
        "request_id": req.id,
        "solver_run_id": int(solver_run_id),
        "human_priority": req.priority,
        "human_urgency": req.urgency,
        "predicted_priority": None if prediction is None else prediction.predicted_priority,
        "predicted_urgency": None if prediction is None else prediction.predicted_urgency,
        "prediction_confidence": None if prediction is None else prediction.confidence,
    }


def create_request_batch(db: Session, user: dict, items: list[dict]):
    if not items:
        raise ValueError("No request items provided")

    created_ids: list[int] = []
    grouped: dict[tuple[str, int], dict] = {}

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"item[{idx}] must be an object")

        normalized_resource_id = _normalize_resource_id(db, item.get("resource_id"), strict=True)
        normalized_time = _normalize_request_time(item.get("time"))
        normalized_quantity = _normalize_quantity(normalized_resource_id, item.get("quantity"))
        normalized_confidence = _normalize_confidence(item.get("confidence", 1.0))
        normalized_source = _normalize_source(item.get("source", "human"))

        key = (normalized_resource_id, normalized_time)
        if key not in grouped:
            grouped[key] = {
                "resource_id": normalized_resource_id,
                "time": normalized_time,
                "quantity": 0.0,
                "priority": _coerce_rank(item.get("priority", None)),
                "urgency": _coerce_rank(item.get("urgency", None)),
                "confidence": normalized_confidence,
                "source": normalized_source,
            }
        grouped[key]["quantity"] = float(grouped[key]["quantity"] or 0.0) + float(normalized_quantity)
        if _coerce_rank(item.get("priority", None)) is not None:
            grouped[key]["priority"] = _coerce_rank(item.get("priority", None))
        if _coerce_rank(item.get("urgency", None)) is not None:
            grouped[key]["urgency"] = _coerce_rank(item.get("urgency", None))

    for (_rid, _time), item in grouped.items():
        existing = db.query(ResourceRequest).filter(
            ResourceRequest.district_code == user["district_code"],
            ResourceRequest.resource_id == item["resource_id"],
            ResourceRequest.time == int(item["time"]),
            ResourceRequest.run_id == 0,
            ResourceRequest.status == "pending",
        ).order_by(ResourceRequest.id.desc()).first()

        if existing is not None:
            existing.quantity = float(existing.quantity or 0.0) + float(item["quantity"])
            if item.get("priority") is not None:
                existing.priority = item.get("priority")
            if item.get("urgency") is not None:
                existing.urgency = item.get("urgency")
            existing.confidence = float(item.get("confidence") or 1.0)
            existing.source = str(item.get("source") or "human")
            existing.queued = 1
            existing.included_in_run = 0
            existing.lifecycle_state = "CREATED"
            prediction = persist_request_prediction(db, existing)
            req = existing
        else:
            req = ResourceRequest(
                district_code=user["district_code"],
                state_code=user["state_code"],
                resource_id=item["resource_id"],
                time=int(item["time"]),
                quantity=float(item["quantity"]),
                priority=item.get("priority"),
                urgency=item.get("urgency"),
                confidence=float(item.get("confidence") or 1.0),
                source=str(item.get("source") or "human"),
                status="pending",
                lifecycle_state="CREATED",
                included_in_run=0,
                queued=1,
                run_id=0,
            )
            db.add(req)
            db.flush()
            prediction = persist_request_prediction(db, req)

        created_ids.append(req.id)

        log_event(
            actor_role="district",
            actor_id=user["district_code"],
            event_type="REQUEST_CREATED",
            payload={
                "resource": req.resource_id,
                "resource_normalized": item["resource_id"],
                "quantity": float(item["quantity"]),
                "time": int(item["time"]),
                "request_id": req.id,
                "human_priority": req.priority,
                "human_urgency": req.urgency,
                "predicted_priority": None if prediction is None else prediction.predicted_priority,
                "predicted_urgency": None if prediction is None else prediction.predicted_urgency,
                "prediction_model_id": None if prediction is None else prediction.model_id,
                "prediction_confidence": None if prediction is None else prediction.confidence,
            },
            db=db,
        )

    _commit_with_retry(db)
    run_id = _start_live_solver_run(db)
    return {"status": "accepted", "request_ids": created_ids, "solver_run_id": run_id}


def _start_live_solver_run(db: Session) -> int:
    stale_cutoff = datetime.utcnow() - timedelta(minutes=30)

    stale_running_rows = db.query(SolverRun)\
        .filter(
            SolverRun.mode == "live",
            SolverRun.status == "running",
            SolverRun.started_at.isnot(None),
            SolverRun.started_at < stale_cutoff,
        )\
        .all()
    if stale_running_rows:
        for row in stale_running_rows:
            row.status = "failed"
        _commit_with_retry(db)

    running_row = db.query(SolverRun)\
        .filter(
            SolverRun.mode == "live",
            SolverRun.status == "running",
        )\
        .order_by(SolverRun.id.desc())\
        .first()
    if running_row is not None:
        return int(running_row.id)

    run = SolverRun(
        scenario_id=None,
        mode="live",
        status="running"
    )

    db.add(run)
    db.commit()
    db.refresh(run)

    worker = threading.Thread(target=_run_solver_job, args=(int(run.id),), daemon=True)
    worker.start()

    return int(run.id)


def trigger_live_solver_run(db: Session) -> int:
    return _start_live_solver_run(db)


# ---------------------------
# Queries
# ---------------------------

def get_requests_for_district(db, district_code):
    rows = db.query(ResourceRequest)\
        .filter(ResourceRequest.district_code == district_code)\
        .order_by(ResourceRequest.created_at.desc())\
        .all()

    _refresh_request_statuses_for_latest_live_run(db)
    return rows


def get_requests_for_state(db: Session, state_code: str):
    rows = db.query(ResourceRequest)\
        .filter(ResourceRequest.state_code == state_code)\
        .order_by(ResourceRequest.created_at.desc())\
        .all()

    _refresh_request_statuses_for_latest_live_run(db)
    return rows


def get_all_requests(db: Session):
    rows = db.query(ResourceRequest)\
        .order_by(ResourceRequest.created_at.desc())\
        .all()

    _refresh_request_statuses_for_latest_live_run(db)
    return rows


def _latest_completed_run(db: Session):
    final_counts = {
        int(r.solver_run_id): int(r.cnt or 0)
        for r in db.query(
            FinalDemand.solver_run_id,
            func.count(FinalDemand.id).label("cnt"),
        ).group_by(FinalDemand.solver_run_id).all()
    }

    live_candidates = db.query(SolverRun)\
        .filter(
            SolverRun.mode == "live",
            SolverRun.status == "completed",
        )\
        .order_by(SolverRun.id.desc())\
        .all()

    for run in live_candidates:
        final_count = final_counts.get(int(run.id), 0)
        if final_count <= 0:
            continue
        return run
    return None


def _latest_live_run(db: Session):
    return _latest_completed_run(db)


def get_latest_dashboard_run(db: Session):
    return _latest_completed_run(db)


def _completed_run_ids_with_signal(db: Session) -> list[int]:
    completed = [
        int(r[0])
        for r in db.query(SolverRun.id)
        .filter(
            SolverRun.status == "completed",
            SolverRun.mode == "live",
        )
        .order_by(SolverRun.id.asc())
        .all()
    ]
    if not completed:
        return []

    final_counts = {
        int(r.solver_run_id): int(r.cnt or 0)
        for r in db.query(
            FinalDemand.solver_run_id,
            func.count(FinalDemand.id).label("cnt"),
        ).group_by(FinalDemand.solver_run_id).all()
    }
    alloc_counts = {
        int(r.solver_run_id): int(r.cnt or 0)
        for r in db.query(
            Allocation.solver_run_id,
            func.count(Allocation.id).label("cnt"),
        ).group_by(Allocation.solver_run_id).all()
    }

    return [
        run_id for run_id in completed
        if final_counts.get(run_id, 0) > 0 or alloc_counts.get(run_id, 0) > 0
    ]


def _latest_completed_run_id_with_signal(db: Session) -> int | None:
    run_ids = [
        int(r[0])
        for r in db.query(SolverRun.id)
        .filter(
            SolverRun.status == "completed",
            SolverRun.mode == "live",
        )
        .order_by(SolverRun.id.desc())
        .all()
    ]
    if not run_ids:
        return None

    for run_id in run_ids:
        has_final = db.query(FinalDemand.id).filter(FinalDemand.solver_run_id == int(run_id)).first() is not None
        if has_final:
            return int(run_id)
        has_alloc = db.query(Allocation.id).filter(Allocation.solver_run_id == int(run_id)).first() is not None
        if has_alloc:
            return int(run_id)

    return int(run_ids[0])


def _snapshot_for_run(run: SolverRun) -> dict | None:
    raw = getattr(run, "summary_snapshot_json", None)
    if not raw:
        return None
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _snapshot_rows_for_run_ids(db: Session, run_ids: list[int]) -> dict[int, dict]:
    if not run_ids:
        return {}
    rows = db.query(SolverRun).filter(SolverRun.id.in_([int(x) for x in run_ids])).all()
    out: dict[int, dict] = {}
    for row in rows:
        snap = _snapshot_for_run(row)
        if snap:
            out[int(row.id)] = snap
    return out


def get_state_allocations(db: Session, state_code: str, limit: int = 100, offset: int = 0):
    latest_run_id = _latest_completed_run_id_with_signal(db)
    if latest_run_id is None:
        return []

    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))

    cache_key = f"state_alloc:{state_code}:{safe_limit}:{safe_offset}:{int(latest_run_id)}"
    return get_or_set_cached(
        cache_key,
        lambda: [
            dict(r._mapping)
            for r in db.execute(
                text(
                    "SELECT * FROM latest_allocations_view "
                    "WHERE state_code = :state_code AND COALESCE(is_unmet, 0) = 0 "
                    "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
                ),
                {
                    "state_code": str(state_code),
                    "limit": int(safe_limit),
                    "offset": int(safe_offset),
                },
            ).fetchall()
        ],
        ttl_seconds=2.0,
    )


def get_state_unmet(db: Session, state_code: str, limit: int = 100, offset: int = 0):
    latest_run_id = _latest_completed_run_id_with_signal(db)
    if latest_run_id is None:
        return []

    district_codes = [
        str(d.district_code)
        for d in db.query(District)
        .filter(District.state_code == state_code)
        .all()
    ]

    if not district_codes:
        return []

    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))

    rows = db.query(Allocation)\
        .from_statement(
            text(
                "SELECT * FROM latest_allocations_view "
                "WHERE district_code IN (SELECT district_code FROM districts WHERE state_code = :state_code) "
                "AND COALESCE(is_unmet, 0) = 1 "
                "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
            )
        )\
        .params(state_code=str(state_code), limit=int(safe_limit), offset=int(safe_offset))\
        .all()

    return [{
        "id": r.id,
        "solver_run_id": r.solver_run_id,
        "resource_id": r.resource_id,
        "district_code": r.district_code,
        "state_code": state_code,
        "time": r.time,
        "unmet_quantity": r.allocated_quantity,
        "unmet_demand": r.allocated_quantity,
    } for r in rows]


def get_national_allocations(db: Session, limit: int = 100, offset: int = 0):
    latest_run_id = _latest_completed_run_id_with_signal(db)
    if latest_run_id is None:
        return []

    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))

    cache_key = f"national_alloc:{safe_limit}:{safe_offset}:{int(latest_run_id)}"
    return get_or_set_cached(
        cache_key,
        lambda: [
            dict(r._mapping)
            for r in db.execute(
                text(
                    "SELECT * FROM latest_allocations_view "
                    "WHERE COALESCE(is_unmet, 0) = 0 "
                    "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
                ),
                {
                    "limit": int(safe_limit),
                    "offset": int(safe_offset),
                },
            ).fetchall()
        ],
        ttl_seconds=2.0,
    )


def get_state_allocations_cursor(
    db: Session,
    state_code: str,
    cursor_id: int | None = None,
    limit: int = 300,
):
    run_ids = _completed_run_ids_with_signal(db)
    if not run_ids:
        return {"rows": [], "next_cursor": None}

    safe_limit = max(1, min(300, int(limit or 300)))
    query = db.query(Allocation)\
        .outerjoin(ResourceRequest, ResourceRequest.id == Allocation.request_id)\
        .filter(
            Allocation.solver_run_id.in_(run_ids),
            Allocation.state_code == str(state_code),
            Allocation.is_unmet == False,
        )

    if cursor_id is not None:
        query = query.filter(Allocation.id < int(cursor_id))

    rows = get_or_set_cached(
        f"state_alloc_cursor:{state_code}:{cursor_id}:{safe_limit}:{max(run_ids)}",
        lambda: query.order_by(
            Allocation.solver_run_id.desc(),
            func.coalesce(ResourceRequest.created_at, Allocation.created_at).desc(),
            ResourceRequest.id.desc(),
            Allocation.time.asc(),
            Allocation.id.desc(),
        ).limit(safe_limit).all(),
        ttl_seconds=2.0,
    )

    next_cursor = (None if len(rows) < safe_limit else int(rows[-1].id))
    return {"rows": rows, "next_cursor": next_cursor}


def get_national_allocations_cursor(
    db: Session,
    cursor_id: int | None = None,
    limit: int = 300,
):
    run_ids = _completed_run_ids_with_signal(db)
    if not run_ids:
        return {"rows": [], "next_cursor": None}

    safe_limit = max(1, min(300, int(limit or 300)))
    query = db.query(Allocation)\
        .outerjoin(ResourceRequest, ResourceRequest.id == Allocation.request_id)\
        .filter(
            Allocation.solver_run_id.in_(run_ids),
            Allocation.is_unmet == False,
        )

    if cursor_id is not None:
        query = query.filter(Allocation.id < int(cursor_id))

    rows = get_or_set_cached(
        f"national_alloc_cursor:{cursor_id}:{safe_limit}:{max(run_ids)}",
        lambda: query.order_by(
            Allocation.solver_run_id.desc(),
            func.coalesce(ResourceRequest.created_at, Allocation.created_at).desc(),
            ResourceRequest.id.desc(),
            Allocation.state_code.asc(),
            Allocation.district_code.asc(),
            Allocation.time.asc(),
            Allocation.id.desc(),
        ).limit(safe_limit).all(),
        ttl_seconds=2.0,
    )

    next_cursor = (None if len(rows) < safe_limit else int(rows[-1].id))
    return {"rows": rows, "next_cursor": next_cursor}


def get_state_allocations_delta(
    db: Session,
    state_code: str,
    since_run_id: int = 0,
    since_allocation_id: int = 0,
    limit: int = 300,
):
    run_ids = _completed_run_ids_with_signal(db)
    if not run_ids:
        return {"rows": [], "latest_run_id": None, "latest_allocation_id": since_allocation_id}

    safe_limit = max(1, min(300, int(limit or 300)))
    since_run = max(0, int(since_run_id or 0))
    since_alloc = max(0, int(since_allocation_id or 0))

    rows = db.query(Allocation)\
        .filter(
            Allocation.solver_run_id.in_(run_ids),
            Allocation.state_code == str(state_code),
            Allocation.is_unmet == False,
            or_(
                Allocation.solver_run_id > since_run,
                and_(Allocation.solver_run_id == since_run, Allocation.id > since_alloc),
            ),
        )\
        .order_by(Allocation.solver_run_id.asc(), Allocation.id.asc())\
        .limit(safe_limit)\
        .all()

    latest_run_id = (max((int(r.solver_run_id) for r in rows), default=since_run) if rows else since_run)
    latest_alloc_id = (max((int(r.id) for r in rows), default=since_alloc) if rows else since_alloc)
    return {"rows": rows, "latest_run_id": latest_run_id, "latest_allocation_id": latest_alloc_id}


def get_national_allocations_delta(
    db: Session,
    since_run_id: int = 0,
    since_allocation_id: int = 0,
    limit: int = 300,
):
    run_ids = _completed_run_ids_with_signal(db)
    if not run_ids:
        return {"rows": [], "latest_run_id": None, "latest_allocation_id": since_allocation_id}

    safe_limit = max(1, min(300, int(limit or 300)))
    since_run = max(0, int(since_run_id or 0))
    since_alloc = max(0, int(since_allocation_id or 0))

    rows = db.query(Allocation)\
        .filter(
            Allocation.solver_run_id.in_(run_ids),
            Allocation.is_unmet == False,
            or_(
                Allocation.solver_run_id > since_run,
                and_(Allocation.solver_run_id == since_run, Allocation.id > since_alloc),
            ),
        )\
        .order_by(Allocation.solver_run_id.asc(), Allocation.id.asc())\
        .limit(safe_limit)\
        .all()

    latest_run_id = (max((int(r.solver_run_id) for r in rows), default=since_run) if rows else since_run)
    latest_alloc_id = (max((int(r.id) for r in rows), default=since_alloc) if rows else since_alloc)
    return {"rows": rows, "latest_run_id": latest_run_id, "latest_allocation_id": latest_alloc_id}


def get_national_unmet(db: Session, limit: int = 100, offset: int = 0):
    latest_run_id = _latest_completed_run_id_with_signal(db)
    if latest_run_id is None:
        return []

    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))

    rows = db.query(Allocation)\
        .from_statement(
            text(
                "SELECT * FROM latest_allocations_view "
                "WHERE COALESCE(is_unmet, 0) = 1 "
                "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
            )
        )\
        .params(limit=int(safe_limit), offset=int(safe_offset))\
        .all()

    return [{
        "id": r.id,
        "solver_run_id": r.solver_run_id,
        "state_code": r.state_code,
        "resource_id": r.resource_id,
        "district_code": r.district_code,
        "time": r.time,
        "unmet_quantity": r.allocated_quantity,
        "unmet_demand": r.allocated_quantity,
    } for r in rows]


def get_state_escalation_candidates(db: Session, state_code: str):
    _refresh_request_statuses_for_latest_live_run(db)
    return db.query(ResourceRequest)\
        .filter(
            ResourceRequest.state_code == state_code,
            ResourceRequest.status.in_(["pending", "allocated", "partial", "unmet", "escalated_state"])
        )\
        .order_by(ResourceRequest.created_at.desc())\
        .all()


def escalate_request_to_national(db: Session, request_id: int, actor_state: str, reason: str | None = None):
    row = db.query(ResourceRequest).filter(ResourceRequest.id == request_id).first()
    if not row:
        raise ValueError("Request not found")

    if str(row.state_code) != str(actor_state):
        raise ValueError("Cannot escalate request outside your state")

    row.status = "escalated_national"
    row.lifecycle_state = "ESCALATED"
    db.commit()
    db.refresh(row)

    log_event(
        actor_role="state",
        actor_id=str(actor_state),
        event_type="ESCALATE_TO_NATIONAL",
        payload={
            "request_id": row.id,
            "district_code": row.district_code,
            "resource_id": row.resource_id,
            "quantity": row.quantity,
            "time": row.time,
            "reason": reason or ""
        }
    )

    return row


def get_national_escalations(db: Session):
    _refresh_request_statuses_for_latest_live_run(db)
    return db.query(ResourceRequest)\
        .filter(ResourceRequest.status == "escalated_national")\
        .order_by(ResourceRequest.created_at.desc())\
        .all()


def resolve_national_escalation(db: Session, request_id: int, decision: str, note: str | None = None):
    row = db.query(ResourceRequest).filter(ResourceRequest.id == request_id).first()
    if not row:
        raise ValueError("Request not found")

    valid = {"allocated", "partial", "unmet"}
    if decision not in valid:
        raise ValueError("Invalid decision")

    row.status = decision
    row.lifecycle_state = _lifecycle_for_status(decision)
    db.commit()
    db.refresh(row)

    log_event(
        actor_role="national",
        actor_id="NATIONAL",
        event_type="NATIONAL_ESCALATION_RESOLVED",
        payload={
            "request_id": row.id,
            "decision": decision,
            "note": note or "",
            "resource_id": row.resource_id,
            "district_code": row.district_code,
            "resolved_at": datetime.utcnow().isoformat()
        }
    )

    return row


def _refresh_request_statuses_for_latest_live_run(db: Session, target_request_ids: list[int] | None = None):
    req_query = db.query(ResourceRequest)
    if target_request_ids:
        req_query = req_query.filter(ResourceRequest.id.in_(target_request_ids))

    requests = req_query.all()
    if not requests:
        return

    by_slot: dict[tuple[int, str, str, int], list[ResourceRequest]] = {}
    changed = False
    for req in requests:
        run_id = int(req.run_id or 0)
        if run_id <= 0:
            if str(req.status or "").lower() == "solving":
                req.status = "pending"
                req.lifecycle_state = "CREATED"
                req.included_in_run = 0
                req.queued = 1
                changed = True
            continue
        key = (run_id, str(req.district_code), str(req.resource_id), int(req.time))
        by_slot.setdefault(key, []).append(req)

    run_ids = sorted({int(r.run_id or 0) for r in requests if int(r.run_id or 0) > 0})
    if not run_ids:
        return

    run_status = {
        int(r.id): str(r.status)
        for r in db.query(SolverRun).filter(SolverRun.id.in_(run_ids)).all()
    }

    slot_alloc_rows = db.query(
        Allocation.solver_run_id,
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("allocated_total")
    ).filter(
        Allocation.solver_run_id.in_(run_ids),
        Allocation.is_unmet == False,
    ).group_by(
        Allocation.solver_run_id,
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    slot_unmet_rows = db.query(
        Allocation.solver_run_id,
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("unmet_total")
    ).filter(
        Allocation.solver_run_id.in_(run_ids),
        Allocation.is_unmet == True,
    ).group_by(
        Allocation.solver_run_id,
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    alloc_map = {
        (int(r.solver_run_id), str(r.district_code), str(r.resource_id), int(r.time)): float(r.allocated_total or 0.0)
        for r in slot_alloc_rows
    }
    unmet_map = {
        (int(r.solver_run_id), str(r.district_code), str(r.resource_id), int(r.time)): float(r.unmet_total or 0.0)
        for r in slot_unmet_rows
    }

    for slot, reqs in by_slot.items():
        run_id, district_code, resource_id, time = slot
        run_state = str(run_status.get(int(run_id), ""))
        if run_state != "completed":
            for req in reqs:
                if req.status != "solving":
                    req.status = "solving"
                    req.lifecycle_state = "SENT_TO_SOLVER"
                    changed = True
                if int(req.included_in_run or 0) != 1:
                    req.included_in_run = 1
                    changed = True
                if int(req.queued or 0) != 0:
                    req.queued = 0
                    changed = True
            continue

        requested_total = float(sum(float(r.quantity or 0.0) for r in reqs))
        allocated_total = alloc_map.get(slot, 0.0)
        unmet_total = unmet_map.get(slot, 0.0)

        for req in reqs:
            requested_qty = float(req.quantity or 0.0)
            allocated_share = 0.0
            unmet_share = 0.0
            if requested_total > 1e-9:
                ratio = requested_qty / requested_total
                allocated_share = allocated_total * ratio
                unmet_share = unmet_total * ratio

            current_status = str(req.status or "").lower()

            if allocated_share >= requested_qty - 1e-9:
                target = "allocated"
            elif allocated_share > 1e-9:
                target = "partial"
            elif unmet_share > 1e-9:
                target = "unmet"
            else:
                target = "failed"

            if current_status == "escalated_national":
                target = "escalated_national"
            elif current_status == "escalated_state" and target in {"partial", "unmet"}:
                target = "escalated_state"

            if req.status != target:
                req.status = target
                changed = True

            lifecycle_target = _lifecycle_for_status(target)
            if str(getattr(req, "lifecycle_state", "") or "") != lifecycle_target:
                req.lifecycle_state = lifecycle_target
                changed = True

            if target in {"allocated", "partial", "unmet", "solving"}:
                if int(req.included_in_run or 0) != 1:
                    req.included_in_run = 1
                    changed = True
                if int(req.queued or 0) != 0:
                    req.queued = 0
                    changed = True
            elif target == "failed":
                if int(req.queued or 0) != 1:
                    req.queued = 1
                    changed = True

    if changed:
        db.commit()


def get_district_requests_view(
    db: Session,
    district_code: str,
    time_filter: int | None = None,
    day_filter: str | None = None,
    latest_only: bool = False,
    limit: int = 100,
    offset: int = 0,
):
    _refresh_request_statuses_for_latest_live_run(db)

    query = db.query(ResourceRequest).filter(ResourceRequest.district_code == district_code)

    if time_filter is not None:
        query = query.filter(ResourceRequest.time == int(time_filter))

    rows = query.order_by(
        func.coalesce(ResourceRequest.run_id, 0).desc(),
        ResourceRequest.created_at.desc(),
        ResourceRequest.id.desc(),
    ).all()

    if day_filter:
        rows = [
            r for r in rows
            if r.created_at and r.created_at.date().isoformat() == day_filter
        ]

    if latest_only:
        latest = _latest_live_run(db)
        if latest is not None:
            rows = [r for r in rows if int(r.run_id or 0) == int(latest.id) and r.status != "solving"]
        else:
            rows = [r for r in rows if r.status != "solving"]

    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))
    rows = rows[safe_offset:safe_offset + safe_limit]

    run_ids = sorted({int(getattr(r, "run_id", 0) or 0) for r in rows if int(getattr(r, "run_id", 0) or 0) > 0})
    alloc_map: dict[tuple[int, str, str, int], float] = {}
    unmet_map: dict[tuple[int, str, str, int], float] = {}

    if run_ids:
        alloc_rows = db.query(
            Allocation.solver_run_id,
            Allocation.district_code,
            Allocation.resource_id,
            Allocation.time,
            func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("allocated_total")
        ).filter(
            Allocation.solver_run_id.in_(run_ids),
            Allocation.is_unmet == False,
            Allocation.district_code == district_code,
        ).group_by(
            Allocation.solver_run_id,
            Allocation.district_code,
            Allocation.resource_id,
            Allocation.time,
        ).all()

        unmet_rows = db.query(
            Allocation.solver_run_id,
            Allocation.district_code,
            Allocation.resource_id,
            Allocation.time,
            func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("unmet_total")
        ).filter(
            Allocation.solver_run_id.in_(run_ids),
            Allocation.is_unmet == True,
            Allocation.district_code == district_code,
        ).group_by(
            Allocation.solver_run_id,
            Allocation.district_code,
            Allocation.resource_id,
            Allocation.time,
        ).all()

        alloc_map = {
            (int(r.solver_run_id), str(r.district_code), str(r.resource_id), int(r.time)): float(r.allocated_total or 0.0)
            for r in alloc_rows
        }
        unmet_map = {
            (int(r.solver_run_id), str(r.district_code), str(r.resource_id), int(r.time)): float(r.unmet_total or 0.0)
            for r in unmet_rows
        }

    final_demand_map: dict[tuple[int, str, str, int], float] = {}
    if run_ids:
        final_rows = db.query(
            FinalDemand.solver_run_id,
            FinalDemand.district_code,
            FinalDemand.resource_id,
            FinalDemand.time,
            func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0).label("final_demand_quantity"),
        ).filter(
            FinalDemand.solver_run_id.in_(run_ids),
            FinalDemand.district_code == district_code,
        ).group_by(
            FinalDemand.solver_run_id,
            FinalDemand.district_code,
            FinalDemand.resource_id,
            FinalDemand.time,
        ).all()
        final_demand_map = {
            (int(r.solver_run_id), str(r.district_code), str(r.resource_id), int(r.time)): float(r.final_demand_quantity or 0.0)
            for r in final_rows
        }

    payload = []

    prediction_rows = db.query(RequestPrediction).filter(
        RequestPrediction.request_id.in_([int(r.id) for r in rows])
    ).order_by(RequestPrediction.created_at.desc(), RequestPrediction.id.desc()).all() if rows else []

    prediction_map: dict[int, RequestPrediction] = {}
    for row in prediction_rows:
        rid = int(row.request_id)
        if rid not in prediction_map:
            prediction_map[rid] = row

    for r in rows:
        run_id = int(getattr(r, "run_id", 0) or 0)
        key = (run_id, str(r.district_code), str(r.resource_id), int(r.time))
        pred = prediction_map.get(int(r.id))

        predicted_priority = None if pred is None else pred.predicted_priority
        predicted_urgency = None if pred is None else pred.predicted_urgency
        predicted_confidence = None if pred is None else float(pred.confidence or 0.0)

        effective_priority, effective_priority_source = _resolve_rank_for_decision(r.priority, predicted_priority, default=1)
        effective_urgency, effective_urgency_source = _resolve_rank_for_decision(r.urgency, predicted_urgency, default=1)

        payload.append({
            "id": r.id,
            "run_id": run_id,
            "district_code": r.district_code,
            "state_code": r.state_code,
            "resource_id": r.resource_id,
            "time": r.time,
            "quantity": float(r.quantity),
            "human_priority": r.priority,
            "human_urgency": r.urgency,
            "priority": r.priority,
            "urgency": r.urgency,
            "predicted_priority": predicted_priority,
            "predicted_urgency": predicted_urgency,
            "confidence": predicted_confidence,
            "prediction_confidence": predicted_confidence,
            "prediction_model_id": None if pred is None else pred.model_id,
            "prediction_explanation": None if pred is None else pred.explanation_json,
            "effective_priority": effective_priority,
            "effective_urgency": effective_urgency,
            "effective_priority_source": effective_priority_source,
            "effective_urgency_source": effective_urgency_source,
            "human_confidence": float(r.confidence),
            "source": r.source,
            "status": r.status,
            "lifecycle_state": getattr(r, "lifecycle_state", _lifecycle_for_status(r.status)),
            "created_at": r.created_at,
            "included_in_run": bool(r.included_in_run),
            "queued": bool(r.queued),
            "allocated_quantity": alloc_map.get(key, 0.0),
            "unmet_quantity": unmet_map.get(key, 0.0),
            "final_demand_quantity": final_demand_map.get(key, 0.0),
            "lineage_consistent": abs((alloc_map.get(key, 0.0) + unmet_map.get(key, 0.0)) - final_demand_map.get(key, 0.0)) <= 1e-6,
        })

    return payload


def get_state_allocation_summary(db: Session, state_code: str):
    run_ids = _completed_run_ids_with_signal(db)
    if not run_ids:
        return {"solver_run_id": None, "rows": []}

    started = time.perf_counter() * 1000.0
    snapshots, snap_db_ms = timed_call(_snapshot_rows_for_run_ids, db, run_ids)
    snap_rows: list[dict] = []
    for run_id in run_ids:
        snap = snapshots.get(int(run_id))
        if not snap:
            continue
        for row in list(snap.get("state_allocation_summary_rows") or []):
            if str(row.get("state_code") or "") == str(state_code):
                snap_rows.append({
                    "solver_run_id": int(run_id),
                    "district_code": str(row.get("district_code") or ""),
                    "resource_id": str(row.get("resource_id") or ""),
                    "time": int(row.get("time") or 0),
                    "allocated_quantity": float(row.get("allocated_quantity") or 0.0),
                    "unmet_quantity": float(row.get("unmet_quantity") or 0.0),
                    "final_demand_quantity": float(row.get("final_demand_quantity") or 0.0),
                    "met": bool(row.get("met", False)),
                    "lineage_consistent": bool(row.get("lineage_consistent", False)),
                })

    if snap_rows:
        consistent_count = sum(1 for row in snap_rows if bool(row.get("lineage_consistent")))
        total_ms = (time.perf_counter() * 1000.0) - started
        log_perf_event(
            endpoint="/state/allocations/summary",
            total_ms=total_ms,
            db_ms=snap_db_ms,
            rows_scanned=len(snap_rows),
            rows_returned=len(snap_rows),
        )
        return {
            "solver_run_id": int(max(run_ids)),
            "rows": snap_rows,
            "lineage": {
                "consistent_rows": int(consistent_count),
                "total_rows": int(len(snap_rows)),
                "all_consistent": int(consistent_count) == int(len(snap_rows)),
            },
            "snapshot_source": True,
        }

    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/state/allocations/summary",
        total_ms=total_ms,
        db_ms=snap_db_ms,
        rows_scanned=0,
        rows_returned=0,
        extra={"snapshot_source": False, "fallback": "disabled"},
    )
    return {
        "solver_run_id": int(max(run_ids)),
        "rows": [],
        "lineage": {"consistent_rows": 0, "total_rows": 0, "all_consistent": True},
        "snapshot_source": False,
    }


def get_national_allocation_summary(db: Session):
    run_ids = _completed_run_ids_with_signal(db)
    if not run_ids:
        return {"solver_run_id": None, "rows": []}

    started = time.perf_counter() * 1000.0
    snapshots, snap_db_ms = timed_call(_snapshot_rows_for_run_ids, db, run_ids)
    snap_rows: list[dict] = []
    for run_id in run_ids:
        snap = snapshots.get(int(run_id))
        if not snap:
            continue
        for row in list(snap.get("national_allocation_summary_rows") or []):
            snap_rows.append({
                "solver_run_id": int(run_id),
                "state_code": str(row.get("state_code") or ""),
                "district_code": str(row.get("district_code") or ""),
                "resource_id": str(row.get("resource_id") or ""),
                "time": int(row.get("time") or 0),
                "allocated_quantity": float(row.get("allocated_quantity") or 0.0),
                "unmet_quantity": float(row.get("unmet_quantity") or 0.0),
                "final_demand_quantity": float(row.get("final_demand_quantity") or 0.0),
                "met": bool(row.get("met", False)),
                "lineage_consistent": bool(row.get("lineage_consistent", False)),
            })

    if snap_rows:
        consistent_count = sum(1 for row in snap_rows if bool(row.get("lineage_consistent")))
        total_ms = (time.perf_counter() * 1000.0) - started
        log_perf_event(
            endpoint="/national/allocations/summary",
            total_ms=total_ms,
            db_ms=snap_db_ms,
            rows_scanned=len(snap_rows),
            rows_returned=len(snap_rows),
        )
        return {
            "solver_run_id": int(max(run_ids)),
            "rows": snap_rows,
            "lineage": {
                "consistent_rows": int(consistent_count),
                "total_rows": int(len(snap_rows)),
                "all_consistent": int(consistent_count) == int(len(snap_rows)),
            },
            "snapshot_source": True,
        }

    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/national/allocations/summary",
        total_ms=total_ms,
        db_ms=snap_db_ms,
        rows_scanned=0,
        rows_returned=0,
        extra={"snapshot_source": False, "fallback": "disabled"},
    )
    return {
        "solver_run_id": int(max(run_ids)),
        "rows": [],
        "lineage": {"consistent_rows": 0, "total_rows": 0, "all_consistent": True},
        "snapshot_source": False,
    }


def get_state_run_history(db: Session, state_code: str, limit: int = 100, offset: int = 0):
    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))
    runs = db.query(SolverRun).filter(SolverRun.status == "completed").order_by(SolverRun.id.desc()).offset(safe_offset).limit(safe_limit).all()
    if not runs:
        return []

    started = time.perf_counter() * 1000.0
    snapshots = {int(r.id): _snapshot_for_run(r) for r in runs}
    if any(snapshots.values()):
        out = []
        for run in runs:
            rid = int(run.id)
            snap = snapshots.get(rid) or {}
            state_totals = (snap.get("state_totals") or {}).get(str(state_code)) or {}
            alloc = float(state_totals.get("allocated_quantity") or 0.0)
            unmet = float(state_totals.get("unmet_quantity") or 0.0)
            demand = alloc + unmet
            out.append({
                "run_id": rid,
                "status": str(run.status),
                "mode": str(run.mode),
                "started_at": run.started_at,
                "total_demand": demand,
                "total_allocated": alloc,
                "total_unmet": unmet,
            })
        total_ms = (time.perf_counter() * 1000.0) - started
        log_perf_event(
            endpoint="/state/run-history",
            total_ms=total_ms,
            db_ms=0.0,
            rows_scanned=len(out),
            rows_returned=len(out),
            extra={"snapshot_source": True},
        )
        return out

    out = []
    for run in runs:
        rid = int(run.id)
        snap = snapshots.get(rid) or {}
        state_totals = (snap.get("state_totals") or {}).get(str(state_code)) or {}
        alloc = float(state_totals.get("allocated_quantity") or 0.0)
        unmet = float(state_totals.get("unmet_quantity") or 0.0)
        out.append({
            "run_id": rid,
            "status": str(run.status),
            "mode": str(run.mode),
            "started_at": run.started_at,
            "total_demand": float(alloc + unmet),
            "total_allocated": alloc,
            "total_unmet": unmet,
        })
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/state/run-history",
        total_ms=total_ms,
        db_ms=0.0,
        rows_scanned=len(out),
        rows_returned=len(out),
        extra={"snapshot_source": True},
    )
    return out


def get_national_run_history(db: Session, limit: int = 100, offset: int = 0):
    safe_limit = max(1, min(200, int(limit or 100)))
    safe_offset = max(0, int(offset or 0))
    runs = db.query(SolverRun).filter(SolverRun.status == "completed").order_by(SolverRun.id.desc()).offset(safe_offset).limit(safe_limit).all()
    if not runs:
        return []

    started = time.perf_counter() * 1000.0
    snapshots = {int(r.id): _snapshot_for_run(r) for r in runs}
    if any(snapshots.values()):
        out = []
        for run in runs:
            rid = int(run.id)
            snap = snapshots.get(rid) or {}
            totals = snap.get("totals") or {}
            out.append({
                "run_id": rid,
                "status": str(run.status),
                "mode": str(run.mode),
                "started_at": run.started_at,
                "total_demand": float(totals.get("final_demand_quantity") or 0.0),
                "total_allocated": float(totals.get("allocated_quantity") or 0.0),
                "total_unmet": float(totals.get("unmet_quantity") or 0.0),
            })
        total_ms = (time.perf_counter() * 1000.0) - started
        log_perf_event(
            endpoint="/national/run-history",
            total_ms=total_ms,
            db_ms=0.0,
            rows_scanned=len(out),
            rows_returned=len(out),
            extra={"snapshot_source": True},
        )
        return out

    out = []
    for run in runs:
        rid = int(run.id)
        snap = snapshots.get(rid) or {}
        totals = snap.get("totals") or {}
        out.append({
            "run_id": rid,
            "status": str(run.status),
            "mode": str(run.mode),
            "started_at": run.started_at,
            "total_demand": float(totals.get("final_demand_quantity") or 0.0),
            "total_allocated": float(totals.get("allocated_quantity") or 0.0),
            "total_unmet": float(totals.get("unmet_quantity") or 0.0),
        })
    total_ms = (time.perf_counter() * 1000.0) - started
    log_perf_event(
        endpoint="/national/run-history",
        total_ms=total_ms,
        db_ms=0.0,
        rows_scanned=len(out),
        rows_returned=len(out),
        extra={"snapshot_source": True},
    )
    return out
