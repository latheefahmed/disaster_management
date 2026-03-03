from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.models.nn_model import NNModel
from app.models.neural_incident_log import NeuralIncidentLog
from app.models.adaptive_parameter import AdaptiveParameter
from app.models.meta_controller_setting import MetaControllerSetting
from app.services.ls_nmc_training_service import run_fake_training

router = APIRouter()


def _get_or_create_setting(db: Session) -> MetaControllerSetting:
    row = db.query(MetaControllerSetting).filter(MetaControllerSetting.id == 1).first()
    if row is None:
        row = MetaControllerSetting(id=1, mode="shadow", influence_pct=0.2, nn_enabled=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("/status")
def meta_controller_status(
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    setting = _get_or_create_setting(db)
    active = db.query(NNModel).filter(NNModel.status == "prod").order_by(NNModel.version.desc()).first()
    last_param = db.query(AdaptiveParameter).order_by(AdaptiveParameter.id.desc()).first()
    incidents_count = int(db.query(NeuralIncidentLog).count())

    influence_pct = float(setting.influence_pct or 0.0)
    if influence_pct <= 1.0:
        influence_pct *= 100.0

    return {
        "enabled": bool(int(setting.nn_enabled or 0) == 1 and active is not None),
        "nn_enabled": bool(int(setting.nn_enabled or 0) == 1),
        "mode": str(setting.mode or "fallback"),
        "influence_pct": float(max(0.0, min(40.0, influence_pct))),
        "active_model_version": None if active is None else int(active.version),
        "fallback_ready": True,
        "last_guardrail_pass": None if last_param is None else bool(last_param.guardrail_passed),
        "last_source": None if last_param is None else str(last_param.source),
        "last_guardrail_result": None if last_param is None else last_param.guardrail_result,
        "last_applied_params": None if last_param is None else last_param.applied_params_json,
        "incident_count": incidents_count,
    }


@router.post("/enable")
def meta_controller_enable(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    enabled = bool((payload or {}).get("enabled", False))
    setting = _get_or_create_setting(db)

    if enabled:
        existing_prod = db.query(NNModel).filter(NNModel.status == "prod").order_by(NNModel.version.desc()).first()
        if existing_prod is None:
            latest = db.query(NNModel).order_by(NNModel.version.desc()).first()
            if latest is None:
                raise HTTPException(status_code=400, detail="No model available to enable")
            latest.status = "prod"
        setting.nn_enabled = 1
        if str(setting.mode or "").lower() == "fallback":
            setting.mode = "shadow"
        db.commit()
        return {"status": "ok", "enabled": True, "mode": str(setting.mode)}

    db.query(NNModel).filter(NNModel.status == "prod").update({"status": "disabled"}, synchronize_session=False)
    setting.nn_enabled = 0
    setting.mode = "fallback"
    db.commit()
    return {"status": "ok", "enabled": False, "mode": "fallback"}


@router.post("/settings")
def update_meta_controller_settings(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    setting = _get_or_create_setting(db)

    if "mode" in (payload or {}):
        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in {"shadow", "blended", "fallback"}:
            raise HTTPException(status_code=400, detail="Invalid mode")
        setting.mode = mode

    if "influence_pct" in (payload or {}):
        influence_pct = float(payload.get("influence_pct") or 0.0)
        setting.influence_pct = max(0.0, min(40.0, influence_pct)) / 100.0

    if "nn_enabled" in (payload or {}):
        setting.nn_enabled = 1 if bool(payload.get("nn_enabled")) else 0

    db.commit()
    db.refresh(setting)
    return {
        "status": "ok",
        "mode": str(setting.mode),
        "influence_pct": float(max(0.0, min(40.0, float(setting.influence_pct or 0.0) * (100.0 if float(setting.influence_pct or 0.0) <= 1.0 else 1.0)))),
        "nn_enabled": bool(int(setting.nn_enabled or 0) == 1),
    }


@router.post("/train/fake")
def train_fake(
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    return run_fake_training(db)


@router.post("/model/promote")
def promote_model(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    version = int((payload or {}).get("model_version"))
    target = db.query(NNModel).filter(NNModel.version == version).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Model version not found")

    db.query(NNModel).filter(NNModel.status == "prod").update({"status": "disabled"}, synchronize_session=False)
    target.status = "prod"
    db.commit()
    return {"status": "ok", "model_version": version}


@router.post("/model/rollback")
def rollback_model(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    target_version = int((payload or {}).get("target_version"))
    target = db.query(NNModel).filter(NNModel.version == target_version).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Target version not found")

    db.query(NNModel).filter(NNModel.status == "prod").update({"status": "disabled"}, synchronize_session=False)
    target.status = "prod"
    db.commit()
    return {"status": "ok", "model_version": target_version}


@router.get("/incidents")
def list_incidents(
    limit: int = 100,
    db: Session = Depends(get_db),
    user=Depends(require_role(["admin"]))
):
    rows = db.query(NeuralIncidentLog).order_by(NeuralIncidentLog.id.desc()).limit(max(1, int(limit))).all()
    return [
        {
            "id": int(r.id),
            "solver_run_id": r.solver_run_id,
            "incident_type": r.incident_type,
            "severity": r.severity,
            "details_json": r.details_json,
            "created_at": r.created_at,
        }
        for r in rows
    ]
