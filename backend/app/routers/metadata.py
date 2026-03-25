from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models.state import State
from app.models.district import District
from app.models.resource import Resource
from app.services.resource_policy import get_resource_policy, get_resource_unit
from app.services.canonical_resources import (
    CANONICAL_RESOURCE_ORDER,
    CANONICAL_RESOURCE_NAME,
    CANONICAL_RESOURCE_UNIT,
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
    # Always project labels/units from canonical resource dictionary.
    # This prevents corrupted DB display names from mismatching a canonical resource_id.
    payload = []
    for rid in CANONICAL_RESOURCE_ORDER:
        db_row = by_id.get(rid)
        canonical_name = CANONICAL_RESOURCE_NAME.get(rid, rid)
        canonical_unit = CANONICAL_RESOURCE_UNIT.get(rid) or get_resource_unit(rid)
        payload.append(
            {
                "resource_id": rid,
                "label": canonical_name,
                "unit": canonical_unit,
                "canonical_name": canonical_name,
                "resource_name": canonical_name,
                "ethical_priority": float(db_row.ethical_priority) if db_row and db_row.ethical_priority is not None else 1.0,
                "category": CANONICAL_RESOURCE_CATEGORY.get(rid),
                "class": CANONICAL_RESOURCE_CLASS.get(rid),
                "count_type": CANONICAL_RESOURCE_COUNT_TYPE.get(rid),
                "max_reasonable_quantity": float(MAX_PER_RESOURCE.get(rid, 0.0)),
                **get_resource_policy(rid),
            }
        )
    return payload


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
