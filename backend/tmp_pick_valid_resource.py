from app.database import SessionLocal
from app.models.district import District
from app.services.kpi_service import get_district_stock_rows, get_state_stock_rows


def pick():
    db=SessionLocal()
    try:
        for d in db.query(District).order_by(District.district_code.asc()).limit(2000).all():
            dcode=str(d.district_code); scode=str(d.state_code)
            drows=get_district_stock_rows(db,dcode)
            srows=get_state_stock_rows(db,scode)
            sidx={str(r.get('resource_id')):r for r in srows}
            for r in drows:
                rid=str(r.get('resource_id') or '')
                ds=float(r.get('district_stock') or 0)
                ss=float(r.get('state_stock') or 0)
                ns=float(r.get('national_stock') or 0)
                if ds>0 and ss>0 and ns>0 and rid in sidx:
                    print('FOUND',dcode,scode,rid,ds,ss,ns)
                    return
        print('NO_MATCH')
    finally:
        db.close()

pick()
