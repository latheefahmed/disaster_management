from __future__ import annotations

from datetime import datetime
from typing import Iterable

import numpy as np
import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import (
    DEMAND_LEARNING_LAMBDA,
    DEMAND_LEARNING_MIN_SAMPLES,
    DEMAND_LEARNING_RIDGE_ALPHA,
    DEMAND_LEARNING_SMOOTHING,
    ENABLE_DEMAND_LEARNING,
)
from app.models.allocation import Allocation
from app.models.demand_learning_event import DemandLearningEvent
from app.models.demand_weight_model import DemandWeightModel
from app.models.request import ResourceRequest
from app.services.audit_service import log_event


def demand_learning_enabled() -> bool:
    return bool(ENABLE_DEMAND_LEARNING)


def _normalize_slot_frame(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["district_code", "resource_id", "time", value_col])

    work = df.copy()
    required = {"district_code", "resource_id", "time", value_col}
    if not required.issubset(work.columns):
        return pd.DataFrame(columns=["district_code", "resource_id", "time", value_col])

    work["district_code"] = work["district_code"].astype(str)
    work["resource_id"] = work["resource_id"].astype(str)
    work["time"] = work["time"].astype(int)
    work[value_col] = work[value_col].astype(float)

    return work.groupby(["district_code", "resource_id", "time"], as_index=False)[value_col].sum()


def _clamp_weights(w_baseline: float, w_human: float) -> tuple[float, float]:
    w_baseline = float(np.clip(w_baseline, 0.0, 2.0))
    w_human = float(np.clip(w_human, 0.0, 2.0))

    if (w_baseline + w_human) < 0.5:
        total = w_baseline + w_human
        if total <= 1e-9:
            return 0.25, 0.25
        scale = 0.5 / total
        w_baseline = float(np.clip(w_baseline * scale, 0.0, 2.0))
        w_human = float(np.clip(w_human * scale, 0.0, 2.0))

    return w_baseline, w_human


def _latest_global_resource_models(db: Session) -> dict[str, DemandWeightModel]:
    rows = db.query(DemandWeightModel).filter(
        DemandWeightModel.resource_id.isnot(None),
        DemandWeightModel.district_code.is_(None),
        DemandWeightModel.time_slot.is_(None),
    ).order_by(DemandWeightModel.created_at.desc(), DemandWeightModel.id.desc()).all()

    out: dict[str, DemandWeightModel] = {}
    for row in rows:
        rid = str(row.resource_id)
        if rid not in out:
            out[rid] = row
    return out


def apply_weight_models_to_merged_demand(db: Session, merged_df: pd.DataFrame) -> tuple[pd.DataFrame, list[int]]:
    if merged_df is None or merged_df.empty:
        return merged_df, []

    work = merged_df.copy()
    work["demand_baseline"] = work["demand_baseline"].fillna(0.0).astype(float)
    work["demand_human"] = work["demand_human"].fillna(0.0).astype(float)

    work["demand"] = work["demand_baseline"] + work["demand_human"]
    if "source_mix" not in work.columns:
        work["source_mix"] = "merged"

    if not demand_learning_enabled():
        return work, []

    models = _latest_global_resource_models(db)
    if not models:
        return work, []

    used_model_ids: set[int] = set()

    for resource_id, model in models.items():
        mask = (
            work["resource_id"].astype(str) == str(resource_id)
        ) & (
            work["demand_mode"].astype(str) == "baseline_plus_human"
        )

        if not mask.any():
            continue

        w_baseline, w_human = _clamp_weights(model.w_baseline, model.w_human)

        work.loc[mask, "demand"] = (
            (w_baseline * work.loc[mask, "demand_baseline"])
            + (w_human * work.loc[mask, "demand_human"])
        )
        work.loc[mask, "source_mix"] = "learned_weighted"
        used_model_ids.add(int(model.id))

    return work, sorted(used_model_ids)


def capture_demand_learning_events(
    db: Session,
    *,
    solver_run_id: int,
    baseline_df: pd.DataFrame,
    human_df: pd.DataFrame,
    final_df: pd.DataFrame,
    request_ids: Iterable[int] | None = None,
):
    if not demand_learning_enabled():
        return 0

    baseline = _normalize_slot_frame(baseline_df, "baseline_demand")
    human = _normalize_slot_frame(human_df, "human_demand")
    final = _normalize_slot_frame(final_df.rename(columns={"demand": "final_demand"}), "final_demand")

    alloc_rows = db.query(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
        func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("qty"),
    ).filter(
        Allocation.solver_run_id == solver_run_id,
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
        Allocation.solver_run_id == solver_run_id,
        Allocation.is_unmet == True,
    ).group_by(
        Allocation.district_code,
        Allocation.resource_id,
        Allocation.time,
    ).all()

    allocated = pd.DataFrame([
        {
            "district_code": str(r.district_code),
            "resource_id": str(r.resource_id),
            "time": int(r.time),
            "allocated": float(r.qty or 0.0),
        }
        for r in alloc_rows
    ]) if alloc_rows else pd.DataFrame(columns=["district_code", "resource_id", "time", "allocated"])

    unmet = pd.DataFrame([
        {
            "district_code": str(r.district_code),
            "resource_id": str(r.resource_id),
            "time": int(r.time),
            "unmet": float(r.qty or 0.0),
        }
        for r in unmet_rows
    ]) if unmet_rows else pd.DataFrame(columns=["district_code", "resource_id", "time", "unmet"])

    if request_ids:
        req_rows = db.query(
            ResourceRequest.district_code,
            ResourceRequest.resource_id,
            ResourceRequest.time,
            func.coalesce(func.avg(ResourceRequest.priority), 1.0).label("priority"),
            func.coalesce(func.avg(ResourceRequest.urgency), 1.0).label("urgency"),
        ).filter(
            ResourceRequest.id.in_(list(request_ids)),
        ).group_by(
            ResourceRequest.district_code,
            ResourceRequest.resource_id,
            ResourceRequest.time,
        ).all()
    else:
        req_rows = []

    pri_urg = pd.DataFrame([
        {
            "district_code": str(r.district_code),
            "resource_id": str(r.resource_id),
            "time": int(r.time),
            "priority": float(r.priority or 1.0),
            "urgency": float(r.urgency or 1.0),
        }
        for r in req_rows
    ]) if req_rows else pd.DataFrame(columns=["district_code", "resource_id", "time", "priority", "urgency"])

    merged = baseline.merge(human, on=["district_code", "resource_id", "time"], how="outer")
    merged = merged.merge(final, on=["district_code", "resource_id", "time"], how="outer")
    merged = merged.merge(allocated, on=["district_code", "resource_id", "time"], how="outer")
    merged = merged.merge(unmet, on=["district_code", "resource_id", "time"], how="outer")
    merged = merged.merge(pri_urg, on=["district_code", "resource_id", "time"], how="left")

    if merged.empty:
        return 0

    merged["baseline_demand"] = merged["baseline_demand"].fillna(0.0)
    merged["human_demand"] = merged["human_demand"].fillna(0.0)
    merged["final_demand"] = merged["final_demand"].fillna(0.0)
    merged["allocated"] = merged["allocated"].fillna(0.0)
    merged["unmet"] = merged["unmet"].fillna(0.0)
    merged["priority"] = merged["priority"].fillna(1.0)
    merged["urgency"] = merged["urgency"].fillna(1.0)

    events = [
        DemandLearningEvent(
            solver_run_id=int(solver_run_id),
            district_code=str(row.district_code),
            resource_id=str(row.resource_id),
            time=int(row.time),
            baseline_demand=float(row.baseline_demand),
            human_demand=float(row.human_demand),
            final_demand=float(row.final_demand),
            allocated=float(row.allocated),
            unmet=float(row.unmet),
            priority=float(row.priority),
            urgency=float(row.urgency),
        )
        for row in merged.itertuples(index=False)
    ]

    if not events:
        return 0

    db.bulk_save_objects(events)
    db.flush()

    log_event(
        actor_role="system",
        actor_id="demand_learning",
        event_type="DEMAND_LEARNING_EVENTS_CAPTURED",
        payload={
            "solver_run_id": int(solver_run_id),
            "rows": len(events),
        },
        db=db,
    )

    return len(events)


def _ridge_fit_two_features(X: np.ndarray, y: np.ndarray, alpha: float) -> tuple[float, float]:
    XtX = X.T @ X
    regularized = XtX + (alpha * np.eye(X.shape[1]))
    Xty = X.T @ y
    w = np.linalg.solve(regularized, Xty)
    return float(w[0]), float(w[1])


def train_demand_weight_models(db: Session) -> dict:
    rows = db.query(DemandLearningEvent).order_by(DemandLearningEvent.created_at.asc(), DemandLearningEvent.id.asc()).all()

    if not rows:
        return {
            "trained_models": 0,
            "reason": "no_learning_events",
            "mean_unmet_reduction": 0.0,
            "coverage_stability": 0.0,
            "weight_drift": 0.0,
        }

    all_df = pd.DataFrame([
        {
            "resource_id": str(r.resource_id),
            "baseline_demand": float(r.baseline_demand),
            "human_demand": float(r.human_demand),
            "final_demand": float(r.final_demand),
            "allocated": float(r.allocated),
            "unmet": float(r.unmet),
            "created_at": r.created_at,
        }
        for r in rows
    ])

    trained_models: list[DemandWeightModel] = []
    drift_values: list[float] = []

    for resource_id, frame in all_df.groupby("resource_id"):
        if len(frame) < int(DEMAND_LEARNING_MIN_SAMPLES):
            continue

        X = frame[["baseline_demand", "human_demand"]].to_numpy(dtype=float)

        over_alloc = np.maximum(frame["allocated"].to_numpy(dtype=float) - frame["final_demand"].to_numpy(dtype=float), 0.0)
        y = (
            frame["final_demand"].to_numpy(dtype=float)
            + frame["unmet"].to_numpy(dtype=float)
            - (float(DEMAND_LEARNING_LAMBDA) * over_alloc)
        )

        w_baseline, w_human = _ridge_fit_two_features(X, y, alpha=float(DEMAND_LEARNING_RIDGE_ALPHA))
        w_baseline, w_human = _clamp_weights(w_baseline, w_human)

        pred = (w_baseline * frame["baseline_demand"].to_numpy(dtype=float)) + (w_human * frame["human_demand"].to_numpy(dtype=float))
        mae = float(np.mean(np.abs(pred - y)))
        denom = max(1.0, float(np.mean(np.abs(y))))
        confidence = float(np.clip(1.0 - (mae / denom), 0.0, 1.0))

        prev = db.query(DemandWeightModel).filter(
            DemandWeightModel.resource_id == str(resource_id),
            DemandWeightModel.district_code.is_(None),
            DemandWeightModel.time_slot.is_(None),
        ).order_by(DemandWeightModel.created_at.desc(), DemandWeightModel.id.desc()).first()

        if prev is not None:
            smooth = float(np.clip(DEMAND_LEARNING_SMOOTHING, 0.0, 1.0))
            w_baseline = float(prev.w_baseline) + (smooth * (w_baseline - float(prev.w_baseline)))
            w_human = float(prev.w_human) + (smooth * (w_human - float(prev.w_human)))
            w_baseline, w_human = _clamp_weights(w_baseline, w_human)
            drift_values.append(abs(float(prev.w_baseline) - w_baseline) + abs(float(prev.w_human) - w_human))

        trained_models.append(DemandWeightModel(
            district_code=None,
            resource_id=str(resource_id),
            time_slot=None,
            w_baseline=w_baseline,
            w_human=w_human,
            confidence=confidence,
            trained_on_start=frame["created_at"].min() if not frame.empty else datetime.utcnow(),
            trained_on_end=frame["created_at"].max() if not frame.empty else datetime.utcnow(),
        ))

    if not trained_models:
        return {
            "trained_models": 0,
            "reason": "insufficient_samples",
            "mean_unmet_reduction": 0.0,
            "coverage_stability": 0.0,
            "weight_drift": 0.0,
        }

    db.add_all(trained_models)
    db.flush()

    mean_unmet = float(all_df["unmet"].mean()) if not all_df.empty else 0.0
    coverage_ratio = np.clip(
        all_df["allocated"].to_numpy(dtype=float) / np.maximum(all_df["final_demand"].to_numpy(dtype=float), 1e-9),
        0.0,
        1.0,
    )
    coverage_stability = float(np.clip(1.0 - np.std(coverage_ratio), 0.0, 1.0)) if coverage_ratio.size else 0.0
    weight_drift = float(np.mean(drift_values)) if drift_values else 0.0

    log_event(
        actor_role="system",
        actor_id="demand_learning",
        event_type="DEMAND_WEIGHT_MODELS_TRAINED",
        payload={
            "trained_models": len(trained_models),
            "mean_unmet_reduction": mean_unmet,
            "coverage_stability": coverage_stability,
            "weight_drift": weight_drift,
        },
        db=db,
    )

    return {
        "trained_models": len(trained_models),
        "mean_unmet_reduction": mean_unmet,
        "coverage_stability": coverage_stability,
        "weight_drift": weight_drift,
    }
