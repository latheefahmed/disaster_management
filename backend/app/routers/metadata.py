from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models.state import State
from app.models.district import District
from app.models.resource import Resource
from app.services.resource_policy import get_resource_policy, get_resource_unit
from app.services.canonical_resources import (
    CANONICAL_RESOURCE_ORDER,
    CANONICAL_RESOURCE_CATEGORY,
    CANONICAL_RESOURCE_CLASS,
    CANONICAL_RESOURCE_COUNT_TYPE,
    MAX_PER_RESOURCE,
)
from app.services.read_model_projector import (
    project_district_snapshot,
    project_state_snapshot,
    project_national_snapshot,
)

router = APIRouter()


@router.get("/states")
def get_states(db: Session = Depends(get_db)):
    rows = db.query(State).all()

    return [
        {
            "state_code": str(r.state_code),
            "state_name": r.state_name
        }
        for r in rows
    ]


@router.get("/districts")
def get_districts(
    state_code: str | None = Query(default=None),
    db: Session = Depends(get_db)
):
    query = db.query(District)

    if state_code:
        normalized = str(state_code).lstrip("0")

        query = query.filter(
            (District.state_code == state_code) |
            (District.state_code == normalized) |
            (District.state_code == state_code.zfill(2))
        )

    rows = query.all()

    return [
        {
            "district_code": str(r.district_code),
            "district_name": r.district_name,
            "state_code": str(r.state_code)
        }
        for r in rows
    ]


@router.get("/resources")
def get_resources(db: Session = Depends(get_db)):
    rows = db.query(Resource).all()
    by_id = {str(r.resource_id): r for r in rows}
    ordered = [by_id[rid] for rid in CANONICAL_RESOURCE_ORDER if rid in by_id]
    if not ordered:
        ordered = list(rows)

    return [
        {
            "resource_id": r.resource_id,
            "label": r.resource_name or r.resource_id,
            "unit": r.unit or get_resource_unit(r.resource_id),
            "canonical_name": r.canonical_name,
            "resource_name": r.resource_name,
            "ethical_priority": r.ethical_priority,
            "category": CANONICAL_RESOURCE_CATEGORY.get(r.resource_id),
            "class": CANONICAL_RESOURCE_CLASS.get(r.resource_id),
            "count_type": CANONICAL_RESOURCE_COUNT_TYPE.get(r.resource_id),
            "max_reasonable_quantity": float(MAX_PER_RESOURCE.get(r.resource_id, 0.0)),
            **get_resource_policy(r.resource_id)
        }
        for r in ordered
    ]


@router.get("/read-model/district/{district_code}")
def get_district_read_model(
    district_code: str,
    db: Session = Depends(get_db),
):
    return project_district_snapshot(db, district_code=str(district_code))


@router.get("/read-model/state/{state_code}")
def get_state_read_model(
    state_code: str,
    db: Session = Depends(get_db),
):
    return project_state_snapshot(db, state_code=str(state_code))


@router.get("/read-model/national")
def get_national_read_model(
    db: Session = Depends(get_db),
):
    return project_national_snapshot(db)
