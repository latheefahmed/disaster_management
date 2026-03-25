import requests, json, sqlite3
BASE='http://127.0.0.1:8000'

def login(u,p):
    r=requests.post(f'{BASE}/auth/login',json={'username':u,'password':p},timeout=30)
    r.raise_for_status()
    return r.json()['access_token']

d=login('district_603','district123')
h={'Authorization':f'Bearer {d}'}
allocs=requests.get(f'{BASE}/district/allocations',headers=h,timeout=60).json()
slot=next((a for a in allocs if float(a.get('allocated_quantity') or 0)>=3),None)
if not slot:
    print(json.dumps({'status':'no_slot_found'}))
    raise SystemExit(0)

resource_id=str(slot['resource_id'])
time_idx=int(slot['time'])
run_id=int(slot['solver_run_id'])

claim_body={'resource_id':resource_id,'time':time_idx,'quantity':2,'claimed_by':'auto_verify','solver_run_id':run_id}
claim=requests.post(f'{BASE}/district/claim',headers=h,json=claim_body,timeout=60)
claim_json=claim.json() if claim.headers.get('content-type','').startswith('application/json') else {'raw':claim.text}

consume=requests.post(f'{BASE}/district/consume',headers=h,json={'resource_id':resource_id,'time':time_idx,'quantity':1,'solver_run_id':run_id},timeout=60)
consume_json=consume.json() if consume.headers.get('content-type','').startswith('application/json') else {'raw':consume.text}

ret=requests.post(f'{BASE}/district/return',headers=h,json={'resource_id':resource_id,'time':time_idx,'quantity':1,'reason':'verify_fields','solver_run_id':run_id},timeout=60)
ret_json=ret.json() if ret.headers.get('content-type','').startswith('application/json') else {'raw':ret.text}

claims=requests.get(f'{BASE}/district/claims',headers=h,timeout=60).json()
cons=requests.get(f'{BASE}/district/consumptions',headers=h,timeout=60).json()
rets=requests.get(f'{BASE}/district/returns',headers=h,timeout=60).json()

def sample(rows):
    for r in rows:
        if isinstance(r,dict) and 'allocation_source_breakdown' in r:
            return {k:r.get(k) for k in ['id','solver_run_id','resource_id','slot_status','dominant_source','has_interstate','interstate_quantity','allocation_source_breakdown','origin_states']}
    return None

print(json.dumps({
    'slot_used': {'resource_id':resource_id,'time':time_idx,'run_id':run_id},
    'claim_status': claim.status_code,
    'consume_status': consume.status_code,
    'return_status': ret.status_code,
    'claim_resp': claim_json,
    'consume_resp': consume_json,
    'return_resp': ret_json,
    'claims_sample': sample(claims if isinstance(claims,list) else []),
    'consumptions_sample': sample(cons if isinstance(cons,list) else []),
    'returns_sample': sample(rets if isinstance(rets,list) else []),
}, indent=2))
