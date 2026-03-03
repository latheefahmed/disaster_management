from sqlalchemy import text
from app.database import SessionLocal
from app.services.kpi_service import compute_district_kpis

DISTRICT = "603"

db = SessionLocal()
try:
    kpi = compute_district_kpis(db, DISTRICT)
    print({"district": DISTRICT, "kpi": kpi})

    rows = db.execute(text("""
        SELECT solver_run_id, resource_id, time, demand_quantity
        FROM final_demands
        WHERE district_code = :district
        ORDER BY solver_run_id DESC, resource_id ASC, time ASC
        LIMIT 40
    """), {"district": DISTRICT}).mappings().all()

    any_fractional = False
    for r in rows:
        qty = float(r["demand_quantity"] or 0.0)
        if abs(qty - round(qty)) > 1e-9:
            any_fractional = True
            break
    print({"sample_rows": len(rows), "fractional_found_in_sample": any_fractional})
finally:
    db.close()
