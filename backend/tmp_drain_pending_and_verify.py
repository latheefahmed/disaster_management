import json, time, requests, sqlite3
BASE='http://127.0.0.1:8000'

def login(u,p):
    r=requests.post(f'{BASE}/auth/login', json={'username':u,'password':p}, timeout=30)
    r.raise_for_status()
    return r.json()['access_token']

t=login('district_603','district123')
h={'Authorization':f'Bearer {t}'}
req_ids=[3382,3383,3384,3385]

tr=requests.post(f'{BASE}/district/run', headers=h, json={}, timeout=180)
tr.raise_for_status()
run_id=int(tr.json().get('solver_run_id') or 0)

for _ in range(60):
    rh=requests.get(f'{BASE}/district/run-history', headers=h, timeout=30).json()
    row=next((x for x in rh if int(x.get('run_id') or 0)==run_id), None)
    if str((row or {}).get('status') or '').lower() in {'completed','failed','failed_reconciliation'}:
        break
    time.sleep(2)

conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()
ph=','.join('?'*len(req_ids))
cur.execute(f"""
SELECT solver_run_id, request_id, source_request_id, resource_id,
       allocation_source_scope, supply_level, origin_state_code, state_code,
       allocated_quantity, is_unmet
FROM allocations
WHERE solver_run_id=?
  AND (request_id IN ({ph}) OR source_request_id IN ({ph}))
ORDER BY id
""", (run_id, *req_ids, *req_ids))
rows=[dict(r) for r in cur.fetchall()]

cur.execute(f"SELECT id, resource_id, quantity, status FROM requests WHERE id IN ({ph}) ORDER BY id", tuple(req_ids))
reqs=[dict(r) for r in cur.fetchall()]

scope={}
for r in rows:
    if int(r.get('is_unmet') or 0)==1:
        continue
    k=str(r.get('allocation_source_scope') or r.get('supply_level') or 'unknown').lower()
    scope[k]=scope.get(k,0.0)+float(r.get('allocated_quantity') or 0)

print(json.dumps({'new_run_id':run_id,'run_row':row,'request_rows':reqs,'alloc_rows':rows,'scope':scope}, indent=2))
conn.close()
