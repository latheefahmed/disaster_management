from __future__ import annotations

import math

BOUNDS = {
    "alpha": (0.5, 2.0),
    "beta": (0.5, 3.0),
    "gamma": (0.0, 3.0),
    "p_mult": (0.5, 3.0),
    "u_mult": (0.5, 3.0),
}

DRIFT_CAP = {
    "alpha": 0.30,
    "beta": 0.40,
    "gamma": 0.40,
    "p_mult": 0.40,
    "u_mult": 0.40,
}


def _finite(params: dict) -> bool:
    for key in ["alpha", "beta", "gamma", "p_mult", "u_mult"]:
        value = params.get(key)
        if value is None or not math.isfinite(float(value)):
            return False
    return True


def _clip(params: dict) -> dict:
    out = dict(params)
    for key, (low, high) in BOUNDS.items():
        out[key] = max(low, min(high, float(out[key])))
    return out


def _ema(current: dict, last_stable: dict | None, lam: float = 0.25) -> dict:
    if not last_stable:
        return current
    out = dict(current)
    for key in ["alpha", "beta", "gamma", "p_mult", "u_mult"]:
        out[key] = lam * float(current[key]) + (1.0 - lam) * float(last_stable.get(key, current[key]))
    return out


def _drift_ok(current: dict, last_stable: dict | None) -> tuple[bool, str | None]:
    if not last_stable:
        return True, None
    for key, cap in DRIFT_CAP.items():
        if abs(float(current[key]) - float(last_stable.get(key, current[key]))) > float(cap):
            return False, f"drift_violation:{key}"
    return True, None


def _sanity_ok(current: dict, context: dict | None) -> tuple[bool, str | None]:
    if not context:
        return True, None
    unmet_ratio = float(context.get("unmet_ratio", 0.0))
    delay_ratio = float(context.get("delay_ratio", 0.0))
    if unmet_ratio > 0.5 and float(current.get("gamma", 0.0)) < 0.2:
        return False, "sanity_violation:gamma"
    if delay_ratio > 0.5 and float(current.get("u_mult", 0.0)) < 0.8:
        return False, "sanity_violation:u_mult"
    return True, None


def validate_and_smooth(raw_params: dict, last_stable: dict | None, context: dict | None = None) -> tuple[bool, dict, str | None]:
    if not _finite(raw_params):
        return False, {}, "nan_output"

    clipped = _clip(raw_params)
    smoothed = _ema(clipped, last_stable=last_stable, lam=0.25)
    smoothed = _clip(smoothed)

    sanity_ok, sanity_reason = _sanity_ok(smoothed, context)
    if not sanity_ok:
        return False, {}, sanity_reason

    drift_ok, drift_reason = _drift_ok(smoothed, last_stable)
    if not drift_ok:
        return False, {}, drift_reason

    return True, smoothed, None
