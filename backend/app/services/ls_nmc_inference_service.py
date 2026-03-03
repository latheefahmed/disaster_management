from __future__ import annotations

import numpy as np
from sqlalchemy.orm import Session

from app.config import NN_ROLLING_WINDOW
from app.models.nn_model import NNModel
from app.models.nn_feature_cache import NNFeatureCache
from app.services.stream_feature_service import FEATURE_COLUMNS


def get_active_prod_model(db: Session) -> NNModel | None:
    return db.query(NNModel).filter(NNModel.status == "prod").order_by(NNModel.version.desc()).first()


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _map_output(sigmoid_out: np.ndarray) -> dict:
    s = sigmoid_out.flatten()
    return {
        "alpha": float(0.5 + s[0] * (2.0 - 0.5)),
        "beta": float(0.5 + s[1] * (3.0 - 0.5)),
        "gamma": float(0.0 + s[2] * (3.0 - 0.0)),
        "p_mult": float(0.5 + s[3] * (3.0 - 0.5)),
        "u_mult": float(0.5 + s[4] * (3.0 - 0.5)),
    }


def _forward(features: np.ndarray, weights: dict) -> np.ndarray:
    w1 = np.array(weights["W1"], dtype=float)
    b1 = np.array(weights["b1"], dtype=float)
    w2 = np.array(weights["W2"], dtype=float)
    b2 = np.array(weights["b2"], dtype=float)
    w3 = np.array(weights["W3"], dtype=float)
    b3 = np.array(weights["b3"], dtype=float)

    z1 = features @ w1 + b1
    a1 = np.maximum(z1, 0.0)
    z2 = a1 @ w2 + b2
    a2 = np.maximum(z2, 0.0)
    z3 = a2 @ w3 + b3
    return _sigmoid(z3)


def _latest_norm_feature_vector(db: Session, solver_run_id: int | None) -> np.ndarray:
    query = db.query(NNFeatureCache)
    if solver_run_id is not None:
        rows = query.filter(NNFeatureCache.solver_run_id == int(solver_run_id)).all()
        if not rows:
            rows = query.order_by(NNFeatureCache.id.desc()).limit(max(1, int(NN_ROLLING_WINDOW))).all()
    else:
        rows = query.order_by(NNFeatureCache.id.desc()).limit(max(1, int(NN_ROLLING_WINDOW))).all()

    if not rows:
        return np.zeros((1, len(FEATURE_COLUMNS)), dtype=float)

    data = []
    for row in rows:
        item = dict(row.norm_features_json or {})
        data.append([float(item.get(col, 0.0)) for col in FEATURE_COLUMNS])
    arr = np.array(data, dtype=float)
    return np.mean(arr, axis=0, keepdims=True)


def infer_raw_params(db: Session, solver_run_id: int | None = None) -> dict:
    model = get_active_prod_model(db)
    if model is None:
        raise RuntimeError("No active prod neural model")

    weights = dict(model.weights_json or {})
    required = {"W1", "b1", "W2", "b2", "W3", "b3"}
    if not required.issubset(set(weights.keys())):
        raise RuntimeError("Model weights missing required tensors")

    x = _latest_norm_feature_vector(db, solver_run_id=solver_run_id)
    y = _forward(x, weights)
    mapped = _map_output(y)
    mapped["model_version"] = int(model.version)
    return mapped
