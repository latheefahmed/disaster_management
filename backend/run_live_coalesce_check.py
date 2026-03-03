from app.database import SessionLocal
from app.models.district import District
from app.services.request_service import create_request_batch


def submit_once(db, district_code: str, state_code: str):
    out = create_request_batch(
        db,
        {"district_code": district_code, "state_code": state_code},
        [
            {
                "resource_id": "R1",
                "time": 0,
                "quantity": 1,
                "priority": 1,
                "urgency": 1,
                "confidence": 1.0,
                "source": "human",
            }
        ],
    )
    return int(out["solver_run_id"])


def main():
    db = SessionLocal()
    try:
        district = db.query(District).filter(District.district_code == "603").first()
        if district is None:
            raise RuntimeError("District 603 not found")

        before_mode = str(district.demand_mode or "baseline_plus_human")
        district.demand_mode = "human_only"
        db.commit()

        first = submit_once(db, "603", str(district.state_code))
        second = submit_once(db, "603", str(district.state_code))

        district.demand_mode = before_mode
        db.commit()

        print("COALESCE_CHECK", {"first_run_id": first, "second_run_id": second, "same_run": first == second})
    finally:
        db.close()


if __name__ == "__main__":
    main()
