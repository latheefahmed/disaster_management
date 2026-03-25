from app.database import SessionLocal
from app.services.kpi_service import get_district_stock_rows, get_state_stock_rows

db = SessionLocal()
try:
    drows = get_district_stock_rows(db, '603')
    srows = get_state_stock_rows(db, '33')
    r35d = next((r for r in drows if r.get('resource_id')=='R35'), None)
    r35s = next((r for r in srows if r.get('resource_id')=='R35'), None)
    print('R35_DISTRICT_VIEW', r35d)
    print('R35_STATE_VIEW', r35s)

    all3 = [r for r in drows if float(r.get('district_stock') or 0)>0 and float(r.get('state_stock') or 0)>0 and float(r.get('national_stock') or 0)>0]
    all3 = sorted(all3, key=lambda r: float(r.get('available_stock') or 0), reverse=True)
    print('ALL3_COUNT', len(all3))
    print('ALL3_TOP5', all3[:5])
finally:
    db.close()
