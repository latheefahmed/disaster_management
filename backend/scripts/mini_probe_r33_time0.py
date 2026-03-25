import json
import math
import time

from app.database import SessionLocal
from app.models.allocation import Allocation
from app.models.district import District
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun
from app.schemas.request import RequestCreate
from app.services.action_service import create_claim, create_return
from app.services.canonical_resources import requires_integer_quantity
from app.services.request_service import create_request, get_district_requests_view

DISTRICT_CODE='603'
TIME_IDX=0
Q_LIST=[500,1500,2500,4000,7000,12000,20000,40000]
MAX_WAIT=240

def wait(db,run):
 s=time.time()
 while time.time()-s<MAX_WAIT:
  db.expire_all(); r=db.query(SolverRun).filter(SolverRun.id==int(run)).first();
  if r and str(r.status).lower() in {'completed','failed','failed_reconciliation'}: return str(r.status).lower()
  time.sleep(1.0)
 return 'timeout'

def summarize(db,req):
 rows=db.query(Allocation).filter(Allocation.request_id==int(req)).all()
 o={'district':0.0,'state':0.0,'neighbor':0.0,'national':0.0,'unmet':0.0}; g={}; ns=set(); tg={}; tra={}
 for r in rows:
  q=float(r.allocated_quantity or 0.0)
  if bool(r.is_unmet): o['unmet']+=q; continue
  sc=str(r.allocation_source_scope or r.supply_level or 'district').lower().strip()
  if sc=='neighbor_state': sc='neighbor'
  if sc not in o: sc='district'
  o[sc]+=q
  t=int(r.time or 0)
  rrid=str(r.resource_id or '')
  code=str(r.allocation_source_code or r.origin_state_code or r.state_code or '')
  g[(sc,code)]=float(g.get((sc,code),0.0))+q
  tg[(t,rrid,sc,code)]=float(tg.get((t,rrid,sc,code),0.0))+q
  tra[(t,rrid)]=float(tra.get((t,rrid),0.0))+q
  if sc=='neighbor' and code: ns.add(code)
 o['neighbor_count']=len(ns); o['neighbors']=sorted(ns); o['groups']=g; o['time_groups']=tg; o['time_resource_alloc']=tra; o['alloc_total']=o['district']+o['state']+o['neighbor']+o['national']
 return o

def do_return(db,user,run,_rid,summary):
 if summary['alloc_total']<=1e-6: return 0.0
 ret=0.0
 for (t,rrid),total in sorted(summary['time_resource_alloc'].items()):
  integer=bool(requires_integer_quantity(rrid))
  claim=float(int(math.floor(float(total)+1e-6))) if integer else float(total)
  if claim<=0: continue
  create_claim(db=db,district_code=user['district_code'],resource_id=rrid,time=int(t),quantity=claim,claimed_by='district_manager',solver_run_id=run)
  for (tg,trid,sc,code),q in summary['time_groups'].items():
   if int(tg)!=int(t) or str(trid)!=str(rrid): continue
   rq=float(int(math.floor(q+1e-6))) if integer else float(q)
   if rq<=0: continue
   ascope='neighbor_state' if sc=='neighbor' else sc
   create_return(db=db,district_code=user['district_code'],state_code=user['state_code'],resource_id=rrid,time=int(t),quantity=rq,reason='manual',solver_run_id=run,allocation_source_scope=ascope,allocation_source_code=(code or None))
   ret+=rq
 return ret

def main():
 db=SessionLocal();
 try:
  d=db.query(District).filter(District.district_code==DISTRICT_CODE).first(); user={'district_code':str(d.district_code),'state_code':str(d.state_code),'role':'district'}
  out=[]
  for q in Q_LIST:
   req=RequestCreate(resource_id='R33',time=TIME_IDX,quantity=float(q),priority=5,urgency=5,confidence=1.0,source='human')
   c=create_request(db,user,req); rid=int(c['request_id']); run=int(c['solver_run_id'])
   rs=wait(db,run); _=get_district_requests_view(db,user['district_code'],latest_only=False,limit=10,offset=0)
   rr=db.query(ResourceRequest).filter(ResourceRequest.id==rid).first(); s=summarize(db,rid); ret=do_return(db,user,run,'R33',s)
   out.append({'qty':q,'request_id':rid,'run_id':run,'run_status':rs,'request_status':str(rr.status if rr else 'missing'),'district':s['district'],'state':s['state'],'interstate':s['neighbor'],'national':s['national'],'unmet':s['unmet'],'neighbor_count':s['neighbor_count'],'neighbors':s['neighbors'],'returned':ret})
  print(json.dumps(out,indent=2))
 finally:
  db.close()

if __name__=='__main__':
 main()
