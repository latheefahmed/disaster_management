import json
import requests
from app.database import SessionLocal
from app.services.kpi_service import get_district_stock_rows

BASE='http://127.0.0.1:8000'

def login(u,p):
    r=requests.post(f'{BASE}/auth/login', json={'username':u,'password':p}, timeout=30)
    r.raise_for_status()
    return r.json()['access_token']

def h(t):
    return {'Authorization': f'Bearer {t}'}


d_token=login('district_603','district123')

# pick resources where state >> district
s=SessionLocal()
try:
    rows=get_district_stock_rows(s,'603')
finally:
    s.close()

cand=[r for r in rows if float(r.get('state_stock') or 0)>float(r.get('district_stock') or 0)*2 and float(r.get('state_stock') or 0)>0]
cand=sorted(cand,key=lambda x: float(x.get('state_stock') or 0)-float(x.get('district_stock') or 0), reverse=True)[:8]

submitted=[]
for i,r in enumerate(cand[:6]):
    d=float(r.get('district_stock') or 0)
    st=float(r.get('state_stock') or 0)
    qty=d + max(10.0, min(st*0.45, st-1 if st>1 else st*0.5))
    body={
        'resource_id': str(r.get('resource_id')),
        'time': 0,
        'quantity': float(qty),
        'priority': 5,
        'urgency': 5,
        'confidence': 1.0,
        'source': 'human'
    }
    rr=requests.post(f'{BASE}/district/request', headers=h(d_token), json=body, timeout=45)
    bid=rr.json() if rr.headers.get('content-type','').startswith('application/json') else {'raw': rr.text}
    submitted.append({'resource_id':body['resource_id'],'qty':body['quantity'],'status':rr.status_code,'resp':bid})

tr=requests.post(f'{BASE}/district/run', headers=h(d_token), json={}, timeout=180)
run_payload=tr.json()
run_id=int(run_payload.get('solver_run_id') or 0)

alloc=requests.get(f'{BASE}/district/allocations', headers=h(d_token), timeout=120)
alloc.raise_for_status()
arr=alloc.json()
req_ids={int(x['resp'].get('request_id') or 0) for x in submitted if isinstance(x.get('resp'),dict)}
rows=[a for a in arr if int(a.get('solver_run_id') or 0)==run_id and int(a.get('request_id') or 0) in req_ids]

scope={}
for a in rows:
    k=str(a.get('allocation_source_scope') or a.get('supply_level') or 'unknown').lower()
    scope[k]=scope.get(k,0.0)+float(a.get('allocated_quantity') or 0)

print(json.dumps({
    'submitted': submitted,
    'run_id': run_id,
    'matched_alloc_rows': rows,
    'scope_totals': scope,
}, indent=2))
