import json, time, requests
BASE='http://127.0.0.1:8000'

def login(u,p):
    r=requests.post(f'{BASE}/auth/login', json={'username':u,'password':p}, timeout=30)
    r.raise_for_status()
    return r.json()['access_token']

t=login('district_603','district123')
h={'Authorization':f'Bearer {t}'}
run_id=1131
req_ids={3381,3382,3383,3384,3385}

for _ in range(40):
    rh=requests.get(f'{BASE}/district/run-history', headers=h, timeout=30).json()
    row=next((x for x in rh if int(x.get('run_id') or 0)==run_id), None)
    st=(row or {}).get('status')
    if str(st).lower() in {'completed','failed','failed_reconciliation'}:
        break
    time.sleep(2)

alloc=requests.get(f'{BASE}/district/allocations', headers=h, timeout=60).json()
rows=[a for a in alloc if int(a.get('solver_run_id') or 0)==run_id and int(a.get('request_id') or 0) in req_ids]
scope={}
for a in rows:
    k=str(a.get('allocation_source_scope') or a.get('supply_level') or 'unknown').lower()
    scope[k]=scope.get(k,0.0)+float(a.get('allocated_quantity') or 0)

print(json.dumps({'run_row':row,'rows_count':len(rows),'scope':scope,'rows':rows}, indent=2))
