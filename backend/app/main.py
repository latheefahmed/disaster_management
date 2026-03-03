import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine, apply_runtime_migrations, SessionLocal

from app.models import (
    user,
    state,
    district,
    resource,
    canonical_resource,
    request,
    allocation,
    claim,
    consumption,
    return_,
    scenario,
    scenario_request,
    scenario_state_stock,
    scenario_national_stock,
    solver_run,
    audit_log,
    scenario_explanation,
    agent_recommendation,
    pool_transaction,
    stock_refill_transaction,
    final_demand,
    demand_weight_model,
    demand_learning_event,
    priority_urgency_model,
    priority_urgency_event,
    request_prediction,
    inventory_snapshot,
    shipment_plan,
    mutual_aid_request,
    mutual_aid_offer,
    state_transfer,
    agent_finding,
    agent_action_log,
    nn_model,
    nn_prediction,
    adaptive_parameter,
    adaptive_metric,
    neural_incident_log,
    meta_controller_setting,
    nn_feature_cache,
)

from app.routers import (
    auth,
    metadata,
    district,
    state,
    national,
    admin,
    meta_controller,
    export,
)
from app.models.state import State
from app.models.district import District
from app.services.read_model_projector import (
    project_district_snapshot,
    project_state_snapshot,
    project_national_snapshot,
)

# ---------------- DATABASE ----------------

Base.metadata.create_all(bind=engine)
if str(os.getenv("APP_SKIP_RUNTIME_MIGRATIONS", "false")).strip().lower() not in {"1", "true", "yes", "on"}:
    apply_runtime_migrations()

# ---------------- APP ----------------

app = FastAPI(title="Disaster Resource Backend")
_read_model_task: asyncio.Task | None = None


async def _read_model_projector_loop():
    while True:
        db = SessionLocal()
        try:
            project_national_snapshot(db)
            for row in db.query(State.state_code).limit(15).all():
                project_state_snapshot(db, str(row.state_code))
            for row in db.query(District.district_code).limit(30).all():
                project_district_snapshot(db, str(row.district_code))
        except Exception:
            pass
        finally:
            db.close()
        await asyncio.sleep(10.0)

# ---------------- CORS ----------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ---------------- ROUTERS ----------------

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(metadata.router, prefix="/metadata", tags=["Metadata"])
app.include_router(district.router, prefix="/district", tags=["District"])
app.include_router(state.router, prefix="/state", tags=["State"])
app.include_router(national.router, prefix="/national", tags=["National"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(meta_controller.router, prefix="/admin/meta-controller", tags=["MetaController"])
app.include_router(export.router, prefix="/export", tags=["Export"])


@app.on_event("startup")
async def _startup_background_projector():
    global _read_model_task
    if str(os.getenv("APP_DISABLE_PROJECTOR", "false")).strip().lower() in {"1", "true", "yes", "on"}:
        return
    if _read_model_task is None or _read_model_task.done():
        _read_model_task = asyncio.create_task(_read_model_projector_loop())


@app.on_event("shutdown")
async def _shutdown_background_projector():
    global _read_model_task
    if _read_model_task is not None:
        _read_model_task.cancel()
        _read_model_task = None
