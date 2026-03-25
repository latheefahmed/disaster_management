from app.database import SessionLocal
from app.models.solver_run import SolverRun
from app.models.scenario_request import ScenarioRequest
from app.models.allocation import Allocation
from sqlalchemy import func


db=SessionLocal()
try:
    rows=(db.query(SolverRun.id, SolverRun.scenario_id).filter(SolverRun.scenario_id.isnot(None)).order_by(SolverRun.id.desc()).limit(250).all())
    found=False
    for rid,sid in rows:
        alloc=float(db.query(func.coalesce(func.sum(Allocation.allocated_quantity),0.0)).filter(Allocation.solver_run_id==rid, Allocation.is_unmet==False).scalar() or 0.0)
        unmet=float(db.query(func.coalesce(func.sum(Allocation.allocated_quantity),0.0)).filter(Allocation.solver_run_id==rid, Allocation.is_unmet==True).scalar() or 0.0)
        if alloc<=0 and unmet<=0:
            continue
        reqs=db.query(ScenarioRequest).filter(ScenarioRequest.scenario_id==sid).all()
        if not reqs:
            continue
        print('RUN',rid,'SCEN',sid,'ALLOC',alloc,'UNMET',unmet)
        for r in reqs[:10]:
            print('REQ',r.district_code,r.state_code,r.resource_id,r.time,r.quantity)
        found=True
        break
    if not found:
        print('NO_NONZERO_SCENARIO_RUN_FOUND')
finally:
    db.close()
