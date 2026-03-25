from app.database import SessionLocal
from app.services.kpi_service import get_district_stock_rows

db=SessionLocal()
try:
    rows=get_district_stock_rows(db,'603')
    cand=[r for r in rows if float(r.get('state_stock') or 0)>0 and float(r.get('national_stock') or 0)<=0 and float(r.get('district_stock') or 0)<=10]
    cand=sorted(cand,key=lambda x: float(x.get('state_stock') or 0), reverse=True)
    print('STATE_ONLY_CAND', len(cand))
    print(cand[:10])

    cand2=[r for r in rows if float(r.get('state_stock') or 0)>0 and float(r.get('national_stock') or 0)>0 and float(r.get('district_stock') or 0)<=5]
    cand2=sorted(cand2,key=lambda x: (float(x.get('state_stock') or 0), -float(x.get('national_stock') or 0)), reverse=True)
    print('LOW_DISTRICT_STATE_NAT_CAND', len(cand2))
    print(cand2[:10])
finally:
    db.close()
