from app.database import SessionLocal
from app.services.kpi_service import get_district_stock_rows

db = SessionLocal()
try:
    rows = get_district_stock_rows(db, '603')
    cands = [r for r in rows if float(r.get('district_stock') or 0)>0 and float(r.get('state_stock') or 0)>0 and float(r.get('national_stock') or 0)>0]
    cands = sorted(cands, key=lambda r: (float(r.get('district_stock',0))+float(r.get('state_stock',0))+float(r.get('national_stock',0))), reverse=True)
    print('COUNT_ALL3', len(cands))
    print('TOP5', cands[:5])
finally:
    db.close()
