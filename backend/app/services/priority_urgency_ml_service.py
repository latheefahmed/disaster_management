from __future__ import annotations

import pickle
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import (
    CORE_ENGINE_ROOT,
    ENABLE_PRIORITY_URGENCY_ML,
    PRIORITY_URGENCY_CONFIDENCE_THRESHOLD,
    PRIORITY_URGENCY_EPOCHS,
    PRIORITY_URGENCY_L2,
    PRIORITY_URGENCY_LEARNING_RATE,
    PRIORITY_URGENCY_MIN_SAMPLES,
)
from app.models.allocation import Allocation
from app.models.priority_urgency_event import PriorityUrgencyEvent
from app.models.priority_urgency_model import PriorityUrgencyModel
from app.models.request import ResourceRequest
from app.models.request_prediction import RequestPrediction
from app.models.resource import Resource
from app.models.scenario_request import ScenarioRequest
from app.services.audit_service import log_event


FEATURE_COLUMNS = [
    "baseline_demand",
    "human_quantity",
    "final_demand",
    "allocated",
    "unmet",
    "severity_index",
    "infrastructure_damage_index",
    "population_exposed",
    "resource_ethical_priority",
    "human_confidence",
    "time",
]


@dataclass
class LogisticModel:
    weights: np.ndarray
    bias: float
    mean: np.ndarray
    std: np.ndarray


def priority_urgency_ml_enabled() -> bool:
    return bool(ENABLE_PRIORITY_URGENCY_ML)


def get_latest_priority_urgency_model_refs(db: Session) -> dict[str, int | None]:
    priority_model = _latest_model(db, "priority", resource_id=None, district_code=None)
    urgency_model = _latest_model(db, "urgency", resource_id=None, district_code=None)
    return {
        "priority_model_id": int(priority_model.id) if priority_model is not None else None,
        "urgency_model_id": int(urgency_model.id) if urgency_model is not None else None,
    }


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40.0, 40.0)))


def _safe_float(value, default: float = 0.0) -> float:
    try:
        out = float(value)
        if np.isnan(out) or np.isinf(out):
            return float(default)
        return out
    except Exception:
        return float(default)


def _load_pickle_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        with open(path, "rb") as handle:
            loaded = pickle.load(handle)
        if isinstance(loaded, pd.DataFrame):
            return loaded
        return pd.DataFrame(loaded)
    except Exception:
        return pd.DataFrame()


def _load_context_map() -> dict[tuple[str, int], dict]:
    models_root = CORE_ENGINE_ROOT / "models"

    severity_df = _load_pickle_frame(models_root / "severity" / "severity_model.pkl")
    exposure_df = _load_pickle_frame(models_root / "exposure_capacity.pkl")
    vulnerability_df = _load_pickle_frame(models_root / "vulnerability" / "vulnerability_composite.pkl")

    context: dict[tuple[str, int], dict] = {}

    if not severity_df.empty:
        severity_df = severity_df.copy()
        if "district_code" in severity_df.columns:
            severity_df["district_code"] = severity_df["district_code"].astype(str)
        if "time_step" in severity_df.columns:
            severity_df["time_step"] = severity_df["time_step"].astype(int)
        elif "time" in severity_df.columns:
            severity_df["time_step"] = severity_df["time"].astype(int)
        else:
            severity_df["time_step"] = 0

        severity_col = "severity_score" if "severity_score" in severity_df.columns else None
        if severity_col is None:
            for c in severity_df.columns:
                if "severity" in c.lower() and c != "time_step":
                    severity_col = c
                    break

        if severity_col is None:
            severity_df["severity_index"] = 0.0
        else:
            severity_df["severity_index"] = severity_df[severity_col].astype(float)

        for row in severity_df[["district_code", "time_step", "severity_index"]].itertuples(index=False):
            context[(str(row.district_code), int(row.time_step))] = {
                "severity_index": _safe_float(row.severity_index, 0.0),
                "infrastructure_damage_index": 0.0,
                "population_exposed": 0.0,
            }

    if not exposure_df.empty:
        work = exposure_df.copy()
        if "district_code" in work.columns:
            work["district_code"] = work["district_code"].astype(str)
        exposure_col = "exposure_score" if "exposure_score" in work.columns else None
        for row in work.itertuples(index=False):
            dc = str(getattr(row, "district_code", ""))
            if not dc:
                continue
            pop_exp = _safe_float(getattr(row, exposure_col, 0.0), 0.0) if exposure_col else 0.0
            for key in [k for k in context.keys() if k[0] == dc] or [(dc, 0)]:
                existing = context.get(key, {"severity_index": 0.0, "infrastructure_damage_index": 0.0, "population_exposed": 0.0})
                existing["population_exposed"] = pop_exp
                context[key] = existing

    if not vulnerability_df.empty:
        work = vulnerability_df.copy()
        if "district_code" in work.columns:
            work["district_code"] = work["district_code"].astype(str)
        vuln_col = "vulnerability_score" if "vulnerability_score" in work.columns else None
        for row in work.itertuples(index=False):
            dc = str(getattr(row, "district_code", ""))
            if not dc:
                continue
            damage = _safe_float(getattr(row, vuln_col, 0.0), 0.0) if vuln_col else 0.0
            for key in [k for k in context.keys() if k[0] == dc] or [(dc, 0)]:
                existing = context.get(key, {"severity_index": 0.0, "infrastructure_damage_index": 0.0, "population_exposed": 0.0})
                existing["infrastructure_damage_index"] = damage
                context[key] = existing

    return context


def _resource_priority_map(db: Session) -> dict[str, float]:
    rows = db.query(Resource).all()
    return {str(r.resource_id): _safe_float(r.ethical_priority, 1.0) for r in rows}


def _fit_logistic_soft_labels(X: np.ndarray, y: np.ndarray) -> LogisticModel:
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)

    Xs = (X - mean) / std

    weights = np.zeros(X.shape[1], dtype=float)
    bias = 0.0

    lr = float(PRIORITY_URGENCY_LEARNING_RATE)
    l2 = float(PRIORITY_URGENCY_L2)
    epochs = int(PRIORITY_URGENCY_EPOCHS)

    for _ in range(max(10, epochs)):
        logits = (Xs @ weights) + bias
        probs = _sigmoid(logits)

        error = probs - y
        grad_w = (Xs.T @ error) / len(Xs) + (l2 * weights)
        grad_b = float(error.mean())

        weights -= lr * grad_w
        bias -= lr * grad_b

    return LogisticModel(weights=weights, bias=float(bias), mean=mean, std=std)


def _predict_proba(model: LogisticModel, X: np.ndarray) -> np.ndarray:
    Xs = (X - model.mean) / np.where(model.std < 1e-8, 1.0, model.std)
    return _sigmoid((Xs @ model.weights) + model.bias)


def _row_to_features(row: dict) -> dict:
    result = {name: _safe_float(row.get(name, 0.0), 0.0) for name in FEATURE_COLUMNS}
    return result


def _clamp_score_1_5(score_0_1: float) -> float:
    mapped = 1.0 + (4.0 * float(np.clip(score_0_1, 0.0, 1.0)))
    return float(np.clip(mapped, 1.0, 5.0))


def _confidence_from_proba(proba: float) -> float:
    return float(np.clip(abs(float(proba) - 0.5) * 2.0, 0.0, 1.0))


def _latest_model(db: Session, model_type: str, resource_id: str | None = None, district_code: str | None = None) -> PriorityUrgencyModel | None:
    query = db.query(PriorityUrgencyModel).filter(PriorityUrgencyModel.model_type == model_type)

    if resource_id is not None:
        query = query.filter(PriorityUrgencyModel.resource_id == str(resource_id))
    else:
        query = query.filter(PriorityUrgencyModel.resource_id.is_(None))

    if district_code is not None:
        query = query.filter(PriorityUrgencyModel.district_code == str(district_code))
    else:
        query = query.filter(PriorityUrgencyModel.district_code.is_(None))

    return query.order_by(PriorityUrgencyModel.version.desc(), PriorityUrgencyModel.id.desc()).first()


def _model_payload_to_runtime(metrics_json: dict | None) -> LogisticModel | None:
    if not metrics_json:
        return None
    model_blob = (metrics_json or {}).get("model")
    if not isinstance(model_blob, dict):
        return None

    try:
        return LogisticModel(
            weights=np.array(model_blob["weights"], dtype=float),
            bias=float(model_blob["bias"]),
            mean=np.array(model_blob["mean"], dtype=float),
            std=np.array(model_blob["std"], dtype=float),
        )
    except Exception:
        return None


def _build_request_feature_row(db: Session, req: ResourceRequest) -> dict:
    baseline_path = CORE_ENGINE_ROOT / "phase3" / "output" / "district_resource_demand.csv"
    baseline_demand = 0.0
    if baseline_path.exists():
        try:
            baseline = pd.read_csv(baseline_path)
            row = baseline[
                (baseline["district_code"].astype(str) == str(req.district_code))
                & (baseline["resource_id"].astype(str) == str(req.resource_id))
                & (baseline["time"].astype(int) == int(req.time))
            ]
            if not row.empty:
                baseline_demand = _safe_float(row.iloc[0].get("demand", 0.0), 0.0)
        except Exception:
            baseline_demand = 0.0

    recent = db.query(
        func.coalesce(func.avg(PriorityUrgencyEvent.unmet), 0.0).label("avg_unmet"),
        func.coalesce(func.avg(PriorityUrgencyEvent.final_demand), 0.0).label("avg_final"),
        func.coalesce(func.avg(PriorityUrgencyEvent.allocated), 0.0).label("avg_alloc"),
    ).filter(
        PriorityUrgencyEvent.district_code == str(req.district_code),
        PriorityUrgencyEvent.resource_id == str(req.resource_id),
    ).first()

    avg_unmet = _safe_float(getattr(recent, "avg_unmet", 0.0), 0.0)
    avg_final = _safe_float(getattr(recent, "avg_final", 0.0), 0.0)
    avg_alloc = _safe_float(getattr(recent, "avg_alloc", 0.0), 0.0)

    unmet_ratio = avg_unmet / max(1.0, avg_final)

    context_map = _load_context_map()
    ctx = context_map.get((str(req.district_code), int(req.time))) or context_map.get((str(req.district_code), 0), {
        "severity_index": 0.0,
        "infrastructure_damage_index": 0.0,
        "population_exposed": 0.0,
    })

    ethical_priority = _resource_priority_map(db).get(str(req.resource_id), 1.0)

    final_est = baseline_demand + _safe_float(req.quantity, 0.0)
    alloc_est = final_est * max(0.0, 1.0 - unmet_ratio)
    unmet_est = max(0.0, final_est - alloc_est)

    return _row_to_features({
        "baseline_demand": baseline_demand,
        "human_quantity": _safe_float(req.quantity, 0.0),
        "final_demand": final_est,
        "allocated": alloc_est,
        "unmet": unmet_est,
        "severity_index": _safe_float(ctx.get("severity_index", 0.0), 0.0),
        "infrastructure_damage_index": _safe_float(ctx.get("infrastructure_damage_index", 0.0), 0.0),
        "population_exposed": _safe_float(ctx.get("population_exposed", 0.0), 0.0),
        "resource_ethical_priority": _safe_float(ethical_priority, 1.0),
        "human_confidence": _safe_float(req.confidence, 1.0),
        "time": _safe_float(req.time, 0.0),
    })


def predict_for_request(db: Session, req: ResourceRequest) -> dict:
    human_priority = None if req.priority is None else float(req.priority)
    human_urgency = None if req.urgency is None else float(req.urgency)

    if not priority_urgency_ml_enabled():
        return {
            "predicted_priority": human_priority,
            "predicted_urgency": human_urgency,
            "model_id": None,
            "confidence": 0.0,
            "explanation": {"reason": "feature_flag_disabled"},
        }

    feature_row = _build_request_feature_row(db, req)
    x = np.array([[feature_row[k] for k in FEATURE_COLUMNS]], dtype=float)

    priority_model_row = _latest_model(db, "priority", resource_id=str(req.resource_id), district_code=None) or _latest_model(db, "priority", resource_id=None, district_code=None)
    urgency_model_row = _latest_model(db, "urgency", resource_id=str(req.resource_id), district_code=None) or _latest_model(db, "urgency", resource_id=None, district_code=None)

    model_id = None
    confidence_values: list[float] = []
    explanation = {"features": []}

    predicted_priority = human_priority
    if human_priority is None and priority_model_row is not None:
        pmodel = _model_payload_to_runtime(priority_model_row.metrics_json)
        if pmodel is not None:
            p = float(_predict_proba(pmodel, x)[0])
            conf = _confidence_from_proba(p)
            confidence_values.append(conf)
            if conf >= float(PRIORITY_URGENCY_CONFIDENCE_THRESHOLD):
                predicted_priority = _clamp_score_1_5(p)
                model_id = int(priority_model_row.id)
            contrib = ((x[0] - pmodel.mean) / np.where(pmodel.std < 1e-8, 1.0, pmodel.std)) * pmodel.weights
            top_idx = np.argsort(np.abs(contrib))[::-1][:3]
            explanation["features"].extend([
                {
                    "feature": FEATURE_COLUMNS[i],
                    "contribution": float(contrib[i]),
                    "model_type": "priority",
                }
                for i in top_idx
            ])

    predicted_urgency = human_urgency
    if human_urgency is None and urgency_model_row is not None:
        umodel = _model_payload_to_runtime(urgency_model_row.metrics_json)
        if umodel is not None:
            p = float(_predict_proba(umodel, x)[0])
            conf = _confidence_from_proba(p)
            confidence_values.append(conf)
            if conf >= float(PRIORITY_URGENCY_CONFIDENCE_THRESHOLD):
                predicted_urgency = _clamp_score_1_5(p)
                if model_id is None:
                    model_id = int(urgency_model_row.id)
            contrib = ((x[0] - umodel.mean) / np.where(umodel.std < 1e-8, 1.0, umodel.std)) * umodel.weights
            top_idx = np.argsort(np.abs(contrib))[::-1][:3]
            explanation["features"].extend([
                {
                    "feature": FEATURE_COLUMNS[i],
                    "contribution": float(contrib[i]),
                    "model_type": "urgency",
                }
                for i in top_idx
            ])

    confidence = float(np.mean(confidence_values)) if confidence_values else 0.0

    return {
        "predicted_priority": predicted_priority,
        "predicted_urgency": predicted_urgency,
        "model_id": model_id,
        "confidence": confidence,
        "explanation": explanation,
    }


def persist_request_prediction(db: Session, req: ResourceRequest) -> RequestPrediction | None:
    if req.priority is not None and req.urgency is not None:
        return None

    if not priority_urgency_ml_enabled():
        return None

    pred = predict_for_request(db, req)

    row = RequestPrediction(
        request_id=int(req.id),
        predicted_priority=pred.get("predicted_priority"),
        predicted_urgency=pred.get("predicted_urgency"),
        model_id=pred.get("model_id"),
        confidence=_safe_float(pred.get("confidence", 0.0), 0.0),
        explanation_json=pred.get("explanation"),
    )
    db.add(row)
    db.flush()

    log_event(
        actor_role="system",
        actor_id="priority_urgency_ml",
        event_type="REQUEST_PREDICTION_CREATED",
        payload={
            "request_id": int(req.id),
            "model_id": pred.get("model_id"),
            "confidence": row.confidence,
            "predicted_priority": row.predicted_priority,
            "predicted_urgency": row.predicted_urgency,
        },
        db=db,
    )

    return row


def resolve_effective_rank(human_value, predicted_value, default: int = 1) -> int:
    if human_value is not None:
        return int(np.clip(int(human_value), 1, 5))
    if predicted_value is not None:
        return int(np.clip(int(round(float(predicted_value))), 1, 5))
    return int(np.clip(int(default), 1, 5))


def _build_slot_maps(
    baseline_df: pd.DataFrame,
    final_df: pd.DataFrame,
    db: Session,
    solver_run_id: int,
) -> tuple[dict, dict, dict, dict]:
    baseline_map = {
        (str(r.district_code), str(r.resource_id), int(r.time)): _safe_float(r.demand, 0.0)
        for r in baseline_df.itertuples(index=False)
    } if baseline_df is not None and not baseline_df.empty else {}

    final_map = {
        (str(r.district_code), str(r.resource_id), int(r.time)): _safe_float(r.demand, 0.0)
        for r in final_df.itertuples(index=False)
    } if final_df is not None and not final_df.empty else {}

    alloc_rows = db.query(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("qty"),
    ).filter(
        Allocation.solver_run_id == int(solver_run_id),
        Allocation.is_unmet == False,
    ).group_by(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    unmet_rows = db.query(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("qty"),
    ).filter(
        Allocation.solver_run_id == int(solver_run_id),
        Allocation.is_unmet == True,
    ).group_by(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    alloc_map = {(str(r.district_code), str(r.resource_id), int(r.time)): _safe_float(r.qty, 0.0) for r in alloc_rows}
    unmet_map = {(str(r.district_code), str(r.resource_id), int(r.time)): _safe_float(r.qty, 0.0) for r in unmet_rows}

    return baseline_map, final_map, alloc_map, unmet_map


def capture_priority_urgency_events(
    db: Session,
    *,
    solver_run_id: int,
    baseline_df: pd.DataFrame,
    final_df: pd.DataFrame,
    request_ids: list[int],
) -> int:
    if not priority_urgency_ml_enabled():
        return 0

    if not request_ids:
        return 0

    reqs = db.query(ResourceRequest).filter(ResourceRequest.id.in_(request_ids)).all()
    if not reqs:
        return 0

    baseline_map, final_map, alloc_map, unmet_map = _build_slot_maps(baseline_df, final_df, db, solver_run_id)
    context_map = _load_context_map()
    ethical_map = _resource_priority_map(db)

    by_slot_requests: dict[tuple[str, str, int], list[ResourceRequest]] = {}
    for req in reqs:
        key = (str(req.district_code), str(req.resource_id), int(req.time))
        by_slot_requests.setdefault(key, []).append(req)

    events: list[PriorityUrgencyEvent] = []

    for req in reqs:
        key = (str(req.district_code), str(req.resource_id), int(req.time))
        slot_reqs = by_slot_requests.get(key, [])

        total_slot_quantity = sum(_safe_float(r.quantity, 0.0) for r in slot_reqs)
        req_qty = _safe_float(req.quantity, 0.0)
        ratio = (req_qty / total_slot_quantity) if total_slot_quantity > 1e-9 else 0.0

        alloc_share = alloc_map.get(key, 0.0) * ratio
        unmet_share = unmet_map.get(key, 0.0) * ratio

        ctx = context_map.get((str(req.district_code), int(req.time))) or context_map.get((str(req.district_code), 0), {
            "severity_index": 0.0,
            "infrastructure_damage_index": 0.0,
            "population_exposed": 0.0,
        })

        events.append(
            PriorityUrgencyEvent(
                solver_run_id=int(solver_run_id),
                district_code=str(req.district_code),
                resource_id=str(req.resource_id),
                time=int(req.time),
                baseline_demand=baseline_map.get(key, 0.0),
                human_quantity=req_qty,
                final_demand=final_map.get(key, baseline_map.get(key, 0.0) + req_qty),
                allocated=alloc_share,
                unmet=unmet_share,
                human_priority=None if req.priority is None else _safe_float(req.priority, 0.0),
                human_urgency=None if req.urgency is None else _safe_float(req.urgency, 0.0),
                severity_index=_safe_float(ctx.get("severity_index", 0.0), 0.0),
                infrastructure_damage_index=_safe_float(ctx.get("infrastructure_damage_index", ethical_map.get(str(req.resource_id), 0.0)), 0.0),
                population_exposed=_safe_float(ctx.get("population_exposed", 0.0), 0.0),
            )
        )

    if not events:
        return 0

    db.bulk_save_objects(events)
    db.flush()

    log_event(
        actor_role="system",
        actor_id="priority_urgency_ml",
        event_type="PRIORITY_URGENCY_EVENTS_CAPTURED",
        payload={
            "solver_run_id": int(solver_run_id),
            "rows": len(events),
        },
        db=db,
    )

    return len(events)


def capture_priority_urgency_events_for_scenario(
    db: Session,
    *,
    solver_run_id: int,
    scenario_id: int,
    baseline_df: pd.DataFrame,
    final_df: pd.DataFrame,
) -> int:
    if not priority_urgency_ml_enabled():
        return 0

    reqs = db.query(ScenarioRequest).filter(ScenarioRequest.scenario_id == int(scenario_id)).all()
    if not reqs:
        return 0

    baseline_map, final_map, alloc_map, unmet_map = _build_slot_maps(baseline_df, final_df, db, solver_run_id)
    context_map = _load_context_map()
    ethical_map = _resource_priority_map(db)

    by_slot_requests: dict[tuple[str, str, int], list[ScenarioRequest]] = {}
    for req in reqs:
        key = (str(req.district_code), str(req.resource_id), int(req.time))
        by_slot_requests.setdefault(key, []).append(req)

    events: list[PriorityUrgencyEvent] = []

    for req in reqs:
        key = (str(req.district_code), str(req.resource_id), int(req.time))
        slot_reqs = by_slot_requests.get(key, [])

        total_slot_quantity = sum(_safe_float(r.quantity, 0.0) for r in slot_reqs)
        req_qty = _safe_float(req.quantity, 0.0)
        ratio = (req_qty / total_slot_quantity) if total_slot_quantity > 1e-9 else 0.0

        alloc_share = alloc_map.get(key, 0.0) * ratio
        unmet_share = unmet_map.get(key, 0.0) * ratio

        ctx = context_map.get((str(req.district_code), int(req.time))) or context_map.get((str(req.district_code), 0), {
            "severity_index": 0.0,
            "infrastructure_damage_index": 0.0,
            "population_exposed": 0.0,
        })

        events.append(
            PriorityUrgencyEvent(
                solver_run_id=int(solver_run_id),
                district_code=str(req.district_code),
                resource_id=str(req.resource_id),
                time=int(req.time),
                baseline_demand=baseline_map.get(key, 0.0),
                human_quantity=req_qty,
                final_demand=final_map.get(key, baseline_map.get(key, 0.0) + req_qty),
                allocated=alloc_share,
                unmet=unmet_share,
                human_priority=None,
                human_urgency=None,
                severity_index=_safe_float(ctx.get("severity_index", 0.0), 0.0),
                infrastructure_damage_index=_safe_float(ctx.get("infrastructure_damage_index", ethical_map.get(str(req.resource_id), 0.0)), 0.0),
                population_exposed=_safe_float(ctx.get("population_exposed", 0.0), 0.0),
            )
        )

    if not events:
        return 0

    db.bulk_save_objects(events)
    db.flush()

    log_event(
        actor_role="system",
        actor_id="priority_urgency_ml",
        event_type="PRIORITY_URGENCY_EVENTS_CAPTURED",
        payload={
            "solver_run_id": int(solver_run_id),
            "scenario_id": int(scenario_id),
            "rows": len(events),
        },
        db=db,
    )

    return len(events)


def _train_model(db: Session, model_type: str) -> dict:
    rows = db.query(PriorityUrgencyEvent).order_by(PriorityUrgencyEvent.created_at.asc(), PriorityUrgencyEvent.id.asc()).all()

    if not rows:
        return {"trained": False, "reason": "no_events", "model_id": None}

    table = pd.DataFrame([
        {
            "resource_id": str(r.resource_id),
            "district_code": str(r.district_code),
            "baseline_demand": _safe_float(r.baseline_demand, 0.0),
            "human_quantity": _safe_float(r.human_quantity, 0.0),
            "final_demand": _safe_float(r.final_demand, 0.0),
            "allocated": _safe_float(r.allocated, 0.0),
            "unmet": _safe_float(r.unmet, 0.0),
            "severity_index": _safe_float(r.severity_index, 0.0),
            "infrastructure_damage_index": _safe_float(r.infrastructure_damage_index, 0.0),
            "population_exposed": _safe_float(r.population_exposed, 0.0),
            "resource_ethical_priority": _safe_float(db.query(Resource.ethical_priority).filter(Resource.resource_id == str(r.resource_id)).scalar(), 1.0),
            "human_confidence": 1.0,
            "time": _safe_float(r.time, 0.0),
            "human_priority": r.human_priority,
            "human_urgency": r.human_urgency,
            "created_at": r.created_at,
        }
        for r in rows
    ])

    target_col = "human_priority" if model_type == "priority" else "human_urgency"
    train = table[table[target_col].notna()].copy()

    if len(train) < int(PRIORITY_URGENCY_MIN_SAMPLES):
        return {"trained": False, "reason": "insufficient_samples", "model_id": None}

    y_raw = train[target_col].astype(float).to_numpy()
    y = np.clip((y_raw - 1.0) / 4.0, 0.0, 1.0)

    X = train[FEATURE_COLUMNS].astype(float).to_numpy()

    model = _fit_logistic_soft_labels(X, y)
    y_hat = _predict_proba(model, X)

    mae = float(np.mean(np.abs(y_hat - y)))
    rmse = float(np.sqrt(np.mean((y_hat - y) ** 2)))

    prev = db.query(PriorityUrgencyModel).filter(
        PriorityUrgencyModel.model_type == model_type,
        PriorityUrgencyModel.resource_id.is_(None),
        PriorityUrgencyModel.district_code.is_(None),
    ).order_by(PriorityUrgencyModel.version.desc(), PriorityUrgencyModel.id.desc()).first()

    next_version = int(prev.version + 1) if prev is not None else 1

    metrics_json = {
        "model": {
            "weights": model.weights.tolist(),
            "bias": model.bias,
            "mean": model.mean.tolist(),
            "std": model.std.tolist(),
            "features": FEATURE_COLUMNS,
        },
        "evaluation": {
            "mae": mae,
            "rmse": rmse,
            "samples": int(len(train)),
        },
    }

    row = PriorityUrgencyModel(
        resource_id=None,
        district_code=None,
        model_type=model_type,
        version=next_version,
        trained_on_start=train["created_at"].min() if not train.empty else datetime.utcnow(),
        trained_on_end=train["created_at"].max() if not train.empty else datetime.utcnow(),
        metrics_json=metrics_json,
    )
    db.add(row)
    db.flush()

    log_event(
        actor_role="system",
        actor_id="priority_urgency_ml",
        event_type="PRIORITY_URGENCY_MODEL_TRAINED",
        payload={
            "model_id": int(row.id),
            "model_type": model_type,
            "version": int(row.version),
            "samples": int(len(train)),
            "mae": mae,
            "rmse": rmse,
        },
        db=db,
    )

    return {
        "trained": True,
        "model_id": int(row.id),
        "version": int(row.version),
        "samples": int(len(train)),
        "mae": mae,
        "rmse": rmse,
    }


def train_priority_urgency_models(db: Session) -> dict:
    if not priority_urgency_ml_enabled():
        return {
            "priority": {"trained": False, "reason": "feature_flag_disabled", "model_id": None},
            "urgency": {"trained": False, "reason": "feature_flag_disabled", "model_id": None},
        }

    priority_result = _train_model(db, "priority")
    urgency_result = _train_model(db, "urgency")
    return {
        "priority": priority_result,
        "urgency": urgency_result,
    }
