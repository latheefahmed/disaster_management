from __future__ import annotations

from app.database import Base, engine, SessionLocal, apply_runtime_migrations
from app.models.state import State
from app.models.district import District
from app.models.resource import Resource
from app.models.user import User
from app.models.solver_run import SolverRun
from app.models.allocation import Allocation
from app.models.mutual_aid_request import MutualAidRequest
from app.models.priority_urgency_model import PriorityUrgencyModel
from app.services.priority_urgency_ml_service import FEATURE_COLUMNS
from app.utils.hashing import hash_password


def _upsert_user(db, username: str, password: str, role: str, state_code: str | None, district_code: str | None):
    row = db.query(User).filter(User.username == username).first()
    if row is None:
        row = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            state_code=state_code,
            district_code=district_code,
        )
        db.add(row)
    else:
        row.password_hash = hash_password(password)
        row.role = role
        row.state_code = state_code
        row.district_code = district_code


def seed_e2e_data() -> None:
    Base.metadata.create_all(bind=engine)
    apply_runtime_migrations()

    db = SessionLocal()
    try:
        for code, name, lat, lon in [
            ("10", "State 10", 12.9716, 77.5946),
            ("20", "State 20", 13.0827, 80.2707),
        ]:
            s = db.query(State).filter(State.state_code == code).first()
            if s is None:
                db.add(State(state_code=code, state_name=name, latitude=lat, longitude=lon))
            else:
                s.state_name = name
                s.latitude = lat
                s.longitude = lon

        for i in range(1, 81):
            dc = f"{1000 + i}"
            d = db.query(District).filter(District.district_code == dc).first()
            if d is None:
                db.add(District(district_code=dc, district_name=f"District {dc}", state_code="10", demand_mode="baseline_plus_human"))

        if db.query(District).filter(District.district_code == "201").first() is None:
            db.add(District(district_code="201", district_name="District 201", state_code="20", demand_mode="baseline_plus_human"))

        resource_rows = [
            ("R1", "food_packets", "person_day_rations"),
            ("R2", "water_liters", "liters"),
            ("R3", "medical_kits", "kits"),
            ("R4", "essential_medicines", "units"),
            ("R5", "rescue_teams", "teams"),
            ("R6", "medical_teams", "teams"),
            ("R7", "volunteers", "people"),
            ("R8", "buses", "vehicles"),
            ("R9", "trucks", "vehicles"),
            ("R10", "boats", "vehicles"),
            ("R11", "helicopters", "vehicles"),
        ]
        for rid, rname, unit in resource_rows:
            r = db.query(Resource).filter(Resource.resource_id == rid).first()
            if r is None:
                db.add(Resource(resource_id=rid, resource_name=rname, unit=unit, canonical_name=rname, ethical_priority=1.0))
            else:
                r.resource_name = rname
                r.unit = unit
                r.canonical_name = rname
                r.ethical_priority = 1.0

        _upsert_user(db, "district_user", "pw", "district", "10", "1001")
        _upsert_user(db, "state_user", "pw", "state", "10", None)
        _upsert_user(db, "national_user", "pw", "national", None, None)
        _upsert_user(db, "admin_user", "pw", "admin", None, None)

        if db.query(PriorityUrgencyModel).filter(PriorityUrgencyModel.model_type == "priority").count() == 0:
            db.add(PriorityUrgencyModel(
                model_type="priority",
                version=1,
                metrics_json={
                    "weights": [0.0 for _ in FEATURE_COLUMNS],
                    "bias": 10.0,
                    "mean": [0.0 for _ in FEATURE_COLUMNS],
                    "std": [1.0 for _ in FEATURE_COLUMNS],
                },
            ))

        if db.query(PriorityUrgencyModel).filter(PriorityUrgencyModel.model_type == "urgency").count() == 0:
            db.add(PriorityUrgencyModel(
                model_type="urgency",
                version=1,
                metrics_json={
                    "weights": [0.0 for _ in FEATURE_COLUMNS],
                    "bias": 10.0,
                    "mean": [0.0 for _ in FEATURE_COLUMNS],
                    "std": [1.0 for _ in FEATURE_COLUMNS],
                },
            ))

        run = db.query(SolverRun).filter(SolverRun.mode == "live", SolverRun.status == "completed").order_by(SolverRun.id.desc()).first()
        if run is None:
            run = SolverRun(mode="live", status="completed")
            db.add(run)
            db.flush()

        existing_alloc = db.query(Allocation).filter(
            Allocation.solver_run_id == run.id,
            Allocation.district_code == "1001",
            Allocation.resource_id == "R10",
            Allocation.time == 1,
            Allocation.is_unmet == False,
        ).first()
        if existing_alloc is None:
            db.add(Allocation(
                solver_run_id=run.id,
                request_id=0,
                resource_id="R10",
                district_code="1001",
                state_code="10",
                origin_state="10",
                time=1,
                allocated_quantity=120.0,
                is_unmet=False,
                claimed_quantity=0.0,
                consumed_quantity=0.0,
                returned_quantity=0.0,
                status="allocated",
            ))

        unmet = db.query(Allocation).filter(
            Allocation.solver_run_id == run.id,
            Allocation.district_code == "1001",
            Allocation.resource_id == "R2",
            Allocation.time == 1,
            Allocation.is_unmet == True,
        ).first()
        if unmet is None:
            db.add(Allocation(
                solver_run_id=run.id,
                request_id=0,
                resource_id="R2",
                district_code="1001",
                state_code="10",
                origin_state="10",
                time=1,
                allocated_quantity=30.0,
                is_unmet=True,
                claimed_quantity=0.0,
                consumed_quantity=0.0,
                returned_quantity=0.0,
                status="unmet",
            ))

        if db.query(MutualAidRequest).filter(
            MutualAidRequest.requesting_state == "20",
            MutualAidRequest.requesting_district == "201",
            MutualAidRequest.resource_id == "R10",
            MutualAidRequest.time == 1,
            MutualAidRequest.status.in_(["open", "partially_filled"]),
        ).first() is None:
            db.add(MutualAidRequest(
                requesting_state="20",
                requesting_district="201",
                resource_id="R10",
                quantity_requested=75.0,
                time=1,
                status="open",
            ))

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed_e2e_data()
    print("E2E seed data ready")
