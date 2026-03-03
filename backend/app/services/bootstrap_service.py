import pandas as pd

from app.database import SessionLocal
from app.config import (
    DATA_PROCESSED_PATH,
    PHASE4_RESOURCE_SCHEMA
)

from app.models.state import State
from app.models.district import District
from app.models.resource import Resource
from app.models.user import User
from app.utils.hashing import hash_password


def bootstrap_geography_and_users():
    db = SessionLocal()

    # --------------------
    # Load CSVs
    # --------------------
    states_df = pd.read_csv(DATA_PROCESSED_PATH / "clean_state_codes.csv")
    districts_df = pd.read_csv(DATA_PROCESSED_PATH / "clean_district_codes.csv")
    resources_df = pd.read_csv(PHASE4_RESOURCE_SCHEMA / "resource_catalog.csv")

    # --------------------
    # Insert States
    # --------------------
    for _, row in states_df.iterrows():
        if not db.get(State, row["state_code"]):
            db.add(State(
                state_code=row["state_code"],
                state_name=row["state_name"]
            ))

    # --------------------
    # Insert Districts
    # --------------------
    for _, row in districts_df.iterrows():
        if not db.get(District, row["district_code"]):
            db.add(District(
                district_code=row["district_code"],
                district_name=row["district_name"],
                state_code=row["state_code"]
            ))

    # --------------------
    # Insert Resources
    # --------------------
    for _, row in resources_df.iterrows():
        if not db.get(Resource, row["resource_id"]):
            db.add(Resource(
                resource_id=row["resource_id"],
                resource_name=row["resource_name"],
                unit=row.get("unit"),
                ethical_priority=row["ethical_priority"],
                canonical_name=row["resource_name"],
            ))
        else:
            existing = db.get(Resource, row["resource_id"])
            existing.resource_name = row["resource_name"]
            existing.unit = row.get("unit")
            existing.ethical_priority = row["ethical_priority"]
            existing.canonical_name = row["resource_name"]

    # --------------------
    # Create Users
    # --------------------
    for _, row in states_df.iterrows():
        username = f"state_{row['state_code']}"
        if not db.get(User, username):
            db.add(User(
                username=username,
                password_hash=hash_password("state123"),
                role="state",
                state_code=row["state_code"]
            ))

    for _, row in districts_df.iterrows():
        username = f"district_{row['district_code']}"
        if not db.get(User, username):
            db.add(User(
                username=username,
                password_hash=hash_password("district123"),
                role="district",
                state_code=row["state_code"],
                district_code=row["district_code"]
            ))

    if not db.get(User, "national_admin"):
        db.add(User(
            username="national_admin",
            password_hash=hash_password("national123"),
            role="national"
        ))

    if not db.get(User, "admin"):
        db.add(User(
            username="admin",
            password_hash=hash_password("admin123"),
            role="admin"
        ))

    db.commit()
    db.close()