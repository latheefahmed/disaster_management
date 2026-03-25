import sqlite3
from app.services.kpi_service import get_state_stock_rows, get_district_stock_rows
from app.database import SessionLocal

db = SessionLocal()
try:
    st = get_state_stock_rows(db, '33')
    d = get_district_stock_rows(db, '603')
    buses_s = [r for r in st if r.get('resource_id') == 'R35']
    buses_d = [r for r in d if r.get('resource_id') == 'R35']
    print('STATE_33_R35', buses_s[0] if buses_s else None)
    print('DISTRICT_603_R35', buses_d[0] if buses_d else None)
finally:
    db.close()
