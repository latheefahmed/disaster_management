from app.database import SessionLocal
from app.models.district import District
from app.services.kpi_service import get_district_stock_rows
from app.services.mutual_aid_service import get_candidate_states

db = SessionLocal()
try:
    picks = []
    for d in db.query(District).all():
        dc = str(d.district_code)
        sc = str(d.state_code)
        cands = get_candidate_states(db, requesting_state=sc, limit=3)
        if not cands:
            continue
        rows = get_district_stock_rows(db, dc)
        r35 = 0.0
        for r in rows:
            if str(r.get('resource_id') or '') == 'R35':
                r35 = float(r.get('district_stock') or 0.0)
                break
        if r35 > 0:
            picks.append((dc, sc, r35, len(cands)))
    picks = sorted(picks, key=lambda x: x[2], reverse=True)
    print('COUNT', len(picks))
    print('TOP20', picks[:20])
finally:
    db.close()
