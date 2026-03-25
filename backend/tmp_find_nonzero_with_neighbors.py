from app.database import SessionLocal
from app.models.solver_run import SolverRun
from app.models.scenario_request import ScenarioRequest
from app.models.allocation import Allocation
from app.services.mutual_aid_service import get_candidate_states
from sqlalchemy import func


db=SessionLocal()
try:
    rows=(db.query(SolverRun.id,SolverRun.scenario_id).filter(SolverRun.scenario_id.isnot(None)).order_by(SolverRun.id.desc()).limit(500).all())
    best=None
    for rid,sid in rows:
        alloc=float(db.query(func.coalesce(func.sum(Allocation.allocated_quantity),0.0)).filter(Allocation.solver_run_id==rid, Allocation.is_unmet==False).scalar() or 0.0)
        unmet=float(db.query(func.coalesce(func.sum(Allocation.allocated_quantity),0.0)).filter(Allocation.solver_run_id==rid, Allocation.is_unmet==True).scalar() or 0.0)
        if alloc<=0 and unmet<=0:
            continue
        req=db.query(ScenarioRequest).filter(ScenarioRequest.scenario_id==sid).first()
        if not req:
            continue
        scode=str(req.state_code)
        cands=get_candidate_states(db, requesting_state=scode, limit=6)
        n=len([c for c in cands if str(c.get('state_code') or '')!=scode])
        if n>0:
            print('FOUND',rid,sid,req.district_code,req.state_code,req.resource_id,req.time,req.quantity,'NEIGH',n,'ALLOC',alloc,'UNMET',unmet)
            best=(rid,sid)
            break
    if not best:
        print('NO_NONZERO_WITH_NEIGHBORS_FOUND')
finally:
    db.close()
