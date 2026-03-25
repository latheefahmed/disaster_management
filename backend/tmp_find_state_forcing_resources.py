from app.database import SessionLocal
from app.services.kpi_service import get_district_stock_rows

db=SessionLocal()
try:
    rows=get_district_stock_rows(db,'603')
    c1=[r for r in rows if float(r.get('district_stock') or 0)<=0 and float(r.get('state_stock') or 0)>0]
    c2=[r for r in rows if float(r.get('district_stock') or 0)>0 and float(r.get('state_stock') or 0)>float(r.get('district_stock') or 0)*2]
    c3=[r for r in rows if float(r.get('district_stock') or 0)>0 and float(r.get('state_stock') or 0)>0 and float(r.get('national_stock') or 0)>0]
    c1=sorted(c1,key=lambda r: float(r.get('state_stock') or 0), reverse=True)
    c2=sorted(c2,key=lambda r: float(r.get('state_stock') or 0)-float(r.get('district_stock') or 0), reverse=True)
    c3=sorted(c3,key=lambda r: float(r.get('state_stock') or 0), reverse=True)
    print('DISTRICT0_STATEPOS_COUNT', len(c1))
    print('DISTRICT0_STATEPOS_TOP10', [{k:x.get(k) for k in ['resource_id','district_stock','state_stock','national_stock','available_stock']} for x in c1[:10]])
    print('STATE_GT_2X_DISTRICT_COUNT', len(c2))
    print('STATE_GT_2X_DISTRICT_TOP10', [{k:x.get(k) for k in ['resource_id','district_stock','state_stock','national_stock','available_stock']} for x in c2[:10]])
    print('ALL3_COUNT', len(c3))
finally:
    db.close()
