import requests, time, json
BASE='http://127.0.0.1:8000'

def login(u,p):
    r=requests.post(f'{BASE}/auth/login',json={'username':u,'password':p},timeout=30)
    r.raise_for_status(); return r.json()['access_token']

d_token=login('district_603','district123')
headers={'Authorization': f'Bearer {d_token}'}

req_payload={'resource_id':'R38','time':0,'quantity':20,'priority':5,'urgency':5,'confidence':1.0,'source':'human'}
req=requests.post(f'{BASE}/district/request',headers=headers,json=req_payload,timeout=60)
req.raise_for_status()
req_id=req.json().get('request_id')

run=requests.post(f'{BASE}/district/run',headers=headers,json={},timeout=300)
run.raise_for_status()
run_id=run.json().get('solver_run_id')

for _ in range(180):
    st=requests.get(f'{BASE}/district/solver-status',headers=headers,timeout=30).json()
    if str(st.get('status','')).lower() in {'completed','failed','failed_reconciliation'}:
        break
    time.sleep(2)

alloc=requests.get(f'{BASE}/district/allocations',headers=headers,timeout=90).json()
rows=[r for r in alloc if int(r.get('solver_run_id') or 0)==int(run_id or 0) and str(r.get('resource_id'))=='R38' and int(r.get('time') or 0)==0 and not bool(r.get('is_unmet'))]
rows=sorted(rows,key=lambda x:int(x.get('id') or 0))
print(json.dumps({'request_id':req_id,'run_id':run_id,'solver_status':st,'rows':rows[:5]},indent=2))
