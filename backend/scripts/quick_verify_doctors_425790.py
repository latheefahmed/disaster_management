import json
from app.database import SessionLocal
from app.services.kpi_service import get_district_stock_rows
from sqlalchemy import text


def main():
    db = SessionLocal()
    try:
        district_code = "603"
        resource_id = "R22"  # doctors
        qty = 425790.0

        req_rows = db.execute(
            text(
                """
            SELECT id, district_code, resource_id, time, quantity, status, lifecycle_state, run_id, created_at
            FROM requests
            WHERE district_code = :dc
              AND resource_id = :rid
              AND time = 0
              AND ABS(quantity - :qty) < 1e-6
            ORDER BY id DESC
            LIMIT 10
                """
            ),
            {"dc": district_code, "rid": resource_id, "qty": qty},
        ).fetchall()

        stock_rows = get_district_stock_rows(db, district_code)
        r22 = next((r for r in stock_rows if str(r.get("resource_id")) == resource_id), None)

        district_stock = float((r22 or {}).get("district_stock") or 0.0)
        state_stock = float((r22 or {}).get("state_stock") or 0.0)
        national_stock = float((r22 or {}).get("national_stock") or 0.0)

        out = {
            "query": {
                "district_code": district_code,
                "resource_id": resource_id,
                "resource_name": "doctors",
                "time": 0,
                "quantity": qty,
            },
            "matching_requests": [dict(r._mapping) for r in req_rows],
            "latest_status": (dict(req_rows[0]._mapping) if req_rows else None),
            "district_stock_now": district_stock,
            "state_stock_now": state_stock,
            "national_stock_now": national_stock,
            "district_has_more_than_qty": district_stock > qty,
            "district_has_at_least_qty": district_stock >= qty,
        }
        print(json.dumps(out, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
