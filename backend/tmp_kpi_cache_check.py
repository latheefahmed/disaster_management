import time
from app.database import SessionLocal
from app.services.kpi_service import compute_district_kpis

db = SessionLocal()
try:
    t1s = time.perf_counter()
    p1 = compute_district_kpis(db, '603', run_window=100)
    t1 = (time.perf_counter() - t1s) * 1000

    t2s = time.perf_counter()
    p2 = compute_district_kpis(db, '603', run_window=100)
    t2 = (time.perf_counter() - t2s) * 1000

    print('KPI1_MS', round(t1,2), 'KPI2_MS', round(t2,2), 'SAME', p1==p2)
finally:
    db.close()
