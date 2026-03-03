from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.adaptive_parameter import AdaptiveParameter
from app.models.meta_controller_setting import MetaControllerSetting
from app.models.neural_incident_log import NeuralIncidentLog
from app.services.adaptive_guard_layer import validate_and_smooth
from app.services.deterministic_fallback_controller import get_params as get_fallback_params
from app.services.ls_nmc_inference_service import infer_raw_params

ENABLE_NN_META_CONTROLLER = True


def _load_setting(db: Session) -> MetaControllerSetting:
    setting = db.query(MetaControllerSetting).filter(MetaControllerSetting.id == 1).first()
    if setting is None:
        setting = MetaControllerSetting(id=1, mode="shadow", influence_pct=0.2, nn_enabled=1, updated_at=datetime.utcnow())
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def _safe_influence_pct(setting: MetaControllerSetting) -> float:
    raw = float(setting.influence_pct or 0.0)
    if raw <= 1.0:
        raw = raw * 100.0
    return max(0.0, min(40.0, raw))


def _blend_params(fallback: dict, neural: dict, influence_pct: float) -> dict:
    ratio = max(0.0, min(1.0, float(influence_pct) / 100.0))
    out = {}
    for key in ["alpha", "beta", "gamma", "p_mult", "u_mult"]:
        base = float(fallback.get(key, 0.0))
        nn = float(neural.get(key, base))
        out[key] = (1.0 - ratio) * base + ratio * nn
    return out


def _log_incident(db: Session, solver_run_id: int | None, incident_type: str, severity: str, details: dict | None = None) -> None:
    db.add(NeuralIncidentLog(
        solver_run_id=solver_run_id,
        incident_type=incident_type,
        severity=severity,
        details_json=details or {},
    ))
    db.flush()


def _persist_adaptive_row(
    db: Session,
    solver_run_id: int | None,
    source: str,
    mode: str,
    influence_pct: float,
    applied: dict,
    fallback_used: int,
    guardrail_passed: int,
    reason: str | None,
    guardrail_result: str | None,
    deterministic: dict,
    neural: dict,
) -> None:
    row = AdaptiveParameter(
        solver_run_id=solver_run_id,
        source=source,
        mode=mode,
        influence_pct=float(influence_pct),
        alpha=float(applied.get("alpha", deterministic.get("alpha", 0.5))),
        beta=float(applied.get("beta", deterministic.get("beta", 0.5))),
        gamma=float(applied.get("gamma", deterministic.get("gamma", 1.0))),
        p_mult=float(applied.get("p_mult", deterministic.get("p_mult", 1.0))),
        u_mult=float(applied.get("u_mult", deterministic.get("u_mult", 1.0))),
        guardrail_passed=int(guardrail_passed),
        fallback_used=int(fallback_used),
        reason=reason,
        guardrail_result=guardrail_result,
        deterministic_params_json={k: float(deterministic.get(k, 0.0)) for k in ["alpha", "beta", "gamma", "p_mult", "u_mult"]},
        nn_params_json={k: float(neural.get(k, deterministic.get(k, 0.0))) for k in ["alpha", "beta", "gamma", "p_mult", "u_mult"]},
        applied_params_json={k: float(applied.get(k, deterministic.get(k, 0.0))) for k in ["alpha", "beta", "gamma", "p_mult", "u_mult"]},
    )
    db.add(row)
    db.flush()


def get_params(db: Session, solver_run_id: int | None = None, context: dict | None = None) -> dict:
    fallback = get_fallback_params(db, solver_run_id=solver_run_id)
    mode = "fallback"

    if not ENABLE_NN_META_CONTROLLER:
        _persist_adaptive_row(
            db,
            solver_run_id=solver_run_id,
            source="fallback",
            mode=mode,
            influence_pct=0.0,
            applied=fallback,
            fallback_used=1,
            guardrail_passed=1,
            reason="controller_disabled_flag",
            guardrail_result="fallback",
            deterministic=fallback,
            neural=fallback,
        )
        db.commit()
        return dict(fallback)

    setting = _load_setting(db)
    setting_mode = str(setting.mode or "fallback").strip().lower()
    enabled = int(setting.nn_enabled or 0) == 1

    if not enabled or setting_mode == "fallback":
        _persist_adaptive_row(
            db,
            solver_run_id=solver_run_id,
            source="fallback",
            mode="fallback",
            influence_pct=0.0,
            applied=fallback,
            fallback_used=1,
            guardrail_passed=1,
            reason="mode_or_toggle_fallback",
            guardrail_result="fallback",
            deterministic=fallback,
            neural=fallback,
        )
        db.commit()
        return dict(fallback)

    try:
        nn = infer_raw_params(db, solver_run_id=solver_run_id)
    except Exception as err:
        _log_incident(db, solver_run_id, "nn_inference_failed", "high", {"error": str(err)})
        _persist_adaptive_row(
            db,
            solver_run_id=solver_run_id,
            source="fallback",
            mode="fallback",
            influence_pct=0.0,
            applied=fallback,
            fallback_used=1,
            guardrail_passed=0,
            reason="nn_inference_failed",
            guardrail_result="fallback",
            deterministic=fallback,
            neural=fallback,
        )
        db.commit()
        return dict(fallback)

    last_stable = {
        "alpha": float(fallback.get("alpha", 0.5)),
        "beta": float(fallback.get("beta", 0.5)),
        "gamma": float(fallback.get("gamma", 1.0)),
        "p_mult": float(fallback.get("p_mult", 1.0)),
        "u_mult": float(fallback.get("u_mult", 1.0)),
    }
    neural_raw = {
        "alpha": float(nn.get("alpha", last_stable["alpha"])),
        "beta": float(nn.get("beta", last_stable["beta"])),
        "gamma": float(nn.get("gamma", last_stable["gamma"])),
        "p_mult": float(nn.get("p_mult", last_stable["p_mult"])),
        "u_mult": float(nn.get("u_mult", last_stable["u_mult"])),
    }

    if setting_mode == "shadow":
        ok, _smoothed, reason = validate_and_smooth(neural_raw, last_stable=last_stable, context=context)
        if not ok:
            _log_incident(db, solver_run_id, "shadow_guardrail_violation", "medium", {"reason": reason})
        _persist_adaptive_row(
            db,
            solver_run_id=solver_run_id,
            source="fallback",
            mode="shadow",
            influence_pct=0.0,
            applied=fallback,
            fallback_used=1,
            guardrail_passed=1 if ok else 0,
            reason=reason,
            guardrail_result="accepted" if ok else str(reason or "rejected"),
            deterministic=fallback,
            neural=neural_raw,
        )
        db.commit()
        return dict(fallback)

    influence_pct = _safe_influence_pct(setting)
    blended = _blend_params(fallback, neural_raw, influence_pct=influence_pct)
    ok, smoothed, reason = validate_and_smooth(blended, last_stable=last_stable, context=context)
    if not ok:
        _log_incident(db, solver_run_id, "blended_guardrail_violation", "high", {"reason": reason})
        _persist_adaptive_row(
            db,
            solver_run_id=solver_run_id,
            source="fallback",
            mode="fallback",
            influence_pct=0.0,
            applied=fallback,
            fallback_used=1,
            guardrail_passed=0,
            reason=reason,
            guardrail_result=str(reason or "rejected"),
            deterministic=fallback,
            neural=neural_raw,
        )
        db.commit()
        return dict(fallback)

    out = dict(smoothed)
    out["source"] = "neural_blend"
    out["mode"] = "blended"
    out["influence_pct"] = float(influence_pct)
    out["model_version"] = nn.get("model_version")

    _persist_adaptive_row(
        db,
        solver_run_id=solver_run_id,
        source="neural_blend",
        mode="blended",
        influence_pct=float(influence_pct),
        applied=out,
        fallback_used=0,
        guardrail_passed=1,
        reason=None,
        guardrail_result="accepted",
        deterministic=fallback,
        neural=neural_raw,
    )
    db.commit()
    return out
