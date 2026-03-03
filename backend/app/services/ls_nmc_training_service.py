from __future__ import annotations

from datetime import datetime

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import NN_ROLLING_WINDOW
from app.models.adaptive_metric import AdaptiveMetric
from app.models.allocation import Allocation
from app.models.final_demand import FinalDemand
from app.models.meta_controller_setting import MetaControllerSetting
from app.models.nn_feature_cache import NNFeatureCache
from app.models.nn_model import NNModel
from app.models.solver_run import SolverRun
from app.services.stream_feature_service import FEATURE_COLUMNS


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _init_weights(input_dim: int) -> dict:
    rng = np.random.default_rng(42)
    return {
        "W1": (rng.normal(0.0, 0.05, size=(input_dim, 32))).tolist(),
        "b1": np.zeros((32,), dtype=float).tolist(),
        "W2": (rng.normal(0.0, 0.05, size=(32, 16))).tolist(),
        "b2": np.zeros((16,), dtype=float).tolist(),
        "W3": (rng.normal(0.0, 0.05, size=(16, 5))).tolist(),
        "b3": np.zeros((5,), dtype=float).tolist(),
    }


def _to_numpy(weights: dict) -> dict:
    return {
        "W1": np.array(weights["W1"], dtype=float),
        "b1": np.array(weights["b1"], dtype=float),
        "W2": np.array(weights["W2"], dtype=float),
        "b2": np.array(weights["b2"], dtype=float),
        "W3": np.array(weights["W3"], dtype=float),
        "b3": np.array(weights["b3"], dtype=float),
    }


def _to_json(weights: dict) -> dict:
    return {k: v.tolist() for k, v in weights.items()}


def _forward(x: np.ndarray, weights: dict) -> tuple[np.ndarray, dict]:
    z1 = x @ weights["W1"] + weights["b1"]
    a1 = np.maximum(z1, 0.0)
    z2 = a1 @ weights["W2"] + weights["b2"]
    a2 = np.maximum(z2, 0.0)
    z3 = a2 @ weights["W3"] + weights["b3"]
    y = _sigmoid(z3)
    cache = {"x": x, "z1": z1, "a1": a1, "z2": z2, "a2": a2, "z3": z3, "y": y}
    return y, cache


def _bounded_targets(unmet_ratio: np.ndarray, delay_ratio: np.ndarray) -> np.ndarray:
    alpha = 0.5 + (1.0 - np.clip(unmet_ratio + 0.3 * delay_ratio, 0.0, 1.0)) * 1.5
    beta = 0.5 + np.clip(unmet_ratio + 0.2 * delay_ratio, 0.0, 1.0) * 2.5
    gamma = np.clip(unmet_ratio + delay_ratio, 0.0, 1.0) * 3.0
    p_mult = 0.5 + np.clip(unmet_ratio, 0.0, 1.0) * 2.5
    u_mult = 0.5 + np.clip(delay_ratio, 0.0, 1.0) * 2.5

    alpha_s = (alpha - 0.5) / (2.0 - 0.5)
    beta_s = (beta - 0.5) / (3.0 - 0.5)
    gamma_s = (gamma - 0.0) / (3.0 - 0.0)
    p_s = (p_mult - 0.5) / (3.0 - 0.5)
    u_s = (u_mult - 0.5) / (3.0 - 0.5)

    return np.stack([alpha_s, beta_s, gamma_s, p_s, u_s], axis=1)


def _train_epoch(x: np.ndarray, y_true: np.ndarray, weights: dict, lr: float = 1e-4, clip_norm: float = 1.0) -> float:
    y_pred, cache = _forward(x, weights)
    diff = y_pred - y_true
    loss = float(np.mean(diff ** 2))

    n = float(x.shape[0])
    dz3 = (2.0 / n) * diff * y_pred * (1.0 - y_pred)
    dW3 = cache["a2"].T @ dz3
    db3 = np.sum(dz3, axis=0)

    da2 = dz3 @ weights["W3"].T
    dz2 = da2 * (cache["z2"] > 0)
    dW2 = cache["a1"].T @ dz2
    db2 = np.sum(dz2, axis=0)

    da1 = dz2 @ weights["W2"].T
    dz1 = da1 * (cache["z1"] > 0)
    dW1 = cache["x"].T @ dz1
    db1 = np.sum(dz1, axis=0)

    grads = [dW1, db1, dW2, db2, dW3, db3]
    norm = np.sqrt(sum(float(np.sum(g ** 2)) for g in grads))
    scale = 1.0 if norm <= clip_norm or norm <= 1e-9 else clip_norm / norm

    weights["W1"] -= lr * dW1 * scale
    weights["b1"] -= lr * db1 * scale
    weights["W2"] -= lr * dW2 * scale
    weights["b2"] -= lr * db2 * scale
    weights["W3"] -= lr * dW3 * scale
    weights["b3"] -= lr * db3 * scale

    return loss


def _load_training_matrix(db: Session, window: int = 30) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = db.query(NNFeatureCache).order_by(NNFeatureCache.id.desc()).limit(max(1, int(window) * 200)).all()
    if not rows:
        return np.zeros((0, len(FEATURE_COLUMNS))), np.zeros((0,)), np.zeros((0,))

    x = []
    unmet = []
    delay = []
    for row in rows:
        feats = dict(row.norm_features_json or {})
        x.append([float(feats.get(c, 0.0)) for c in FEATURE_COLUMNS])
        unmet.append(float(feats.get("unmet_ratio_last_run", 0.0)))
        delay.append(float(feats.get("avg_delay_last_5", 0.0)))

    x_arr = np.array(x, dtype=float)
    unmet_arr = np.array(unmet, dtype=float)
    delay_arr = np.array(delay, dtype=float)
    return x_arr, unmet_arr, delay_arr


def save_model(db: Session, weights: dict, status: str = "staging") -> NNModel:
    latest = db.query(NNModel).order_by(NNModel.version.desc()).first()
    next_version = 1 if latest is None else int(latest.version) + 1

    row = NNModel(
        model_name="ls_nmc",
        version=next_version,
        status=status,
        artifact_uri=f"memory://ls_nmc/{next_version}",
        feature_spec_json={
            "rolling_window": NN_ROLLING_WINDOW,
            "features": FEATURE_COLUMNS,
            "architecture": "Dense(32)->ReLU->Dense(16)->ReLU->Dense(5)->Sigmoid",
        },
        weights_json=weights,
        promoted_at=(datetime.utcnow() if status == "prod" else None),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def run_fake_training(db: Session) -> dict:
    weights = _init_weights(input_dim=len(FEATURE_COLUMNS))
    model = save_model(db, weights=weights, status="staging")
    return {
        "status": "ok",
        "model_version": int(model.version),
        "mode": "fake",
    }


def online_train_after_run(db: Session, solver_run_id: int) -> dict:
    setting = db.query(MetaControllerSetting).filter(MetaControllerSetting.id == 1).first()
    if setting is not None and str(setting.mode) == "fallback":
        return {"status": "skipped", "reason": "fallback_mode"}

    x, unmet, delay = _load_training_matrix(db, window=NN_ROLLING_WINDOW)
    if x.shape[0] == 0:
        return {"status": "skipped", "reason": "no_features"}

    y_target = _bounded_targets(unmet, delay)

    latest = db.query(NNModel).order_by(NNModel.version.desc()).first()
    if latest is None or latest.weights_json is None:
        weights = _to_numpy(_init_weights(input_dim=x.shape[1]))
    else:
        weights = _to_numpy(dict(latest.weights_json))

    best_loss = float("inf")
    patience = 3
    patience_left = patience
    losses = []

    for _epoch in range(20):
        idx = np.random.permutation(x.shape[0])
        batch_idx = idx[: min(64, x.shape[0])]
        xb = x[batch_idx]
        yb = y_target[batch_idx]

        mse_loss = _train_epoch(xb, yb, weights, lr=5e-5, clip_norm=1.0)

        pred, _cache = _forward(xb, weights)
        volatility = float(np.mean(np.abs(np.diff(pred, axis=0)))) if pred.shape[0] > 1 else 0.0
        composite = float(mse_loss + np.mean(unmet) + np.mean(delay) + 0.05 * volatility)
        losses.append(composite)

        if composite + 1e-8 < best_loss:
            best_loss = composite
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    unstable = len(losses) >= 3 and losses[-1] > losses[0] * 1.2
    if unstable and setting is not None:
        setting.mode = "shadow"
        db.add(setting)

    model = save_model(db, weights=_to_json(weights), status="staging")

    unmet_ratio = float(db.query(func.coalesce(func.sum(Allocation.allocated_quantity), 0.0)).filter(
        Allocation.solver_run_id == int(solver_run_id),
        Allocation.is_unmet == True,
    ).scalar() or 0.0)

    total = float(db.query(func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0)).filter(
        FinalDemand.solver_run_id == int(solver_run_id),
    ).scalar() or 0.0)

    unmet_ratio = 0.0 if total <= 1e-9 else unmet_ratio / total
    avg_delay = float(np.mean(delay)) if delay.size > 0 else 0.0
    volatility = float(np.std(losses)) if len(losses) > 1 else 0.0
    stability_score = max(0.0, 100.0 - (100.0 * min(1.0, volatility + unmet_ratio)))

    db.add(AdaptiveMetric(
        solver_run_id=int(solver_run_id),
        model_version=int(model.version),
        unmet_ratio=float(unmet_ratio),
        avg_delay_hours=float(avg_delay),
        volatility=float(volatility),
        stability_score=float(stability_score),
    ))
    db.commit()

    return {
        "status": "ok",
        "model_version": int(model.version),
        "best_loss": float(best_loss),
        "unstable": bool(unstable),
    }
