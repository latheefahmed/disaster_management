import requests, json
BASE='http://127.0.0.1:8000'

def login(u,p):
    r=requests.post(f'{BASE}/auth/login',json={'username':u,'password':p},timeout=30)
    r.raise_for_status()
    return r.json()['access_token']

t=login('district_603','district123')
h={'Authorization':f'Bearer {t}'}
claims=requests.get(f'{BASE}/district/claims',headers=h,timeout=60).json()
cons=requests.get(f'{BASE}/district/consumptions',headers=h,timeout=60).json()
rets=requests.get(f'{BASE}/district/returns',headers=h,timeout=60).json()

def sample(rows):
    for r in rows:
        if isinstance(r,dict) and 'allocation_source_breakdown' in r:
            return {
                'id': r.get('id'),
                'solver_run_id': r.get('solver_run_id'),
                'resource_id': r.get('resource_id'),
                'slot_status': r.get('slot_status'),
                'dominant_source': r.get('dominant_source'),
                'has_interstate': r.get('has_interstate'),
                'interstate_quantity': r.get('interstate_quantity'),
                'allocation_source_breakdown': r.get('allocation_source_breakdown'),
                'origin_states': r.get('origin_states'),
            }
    return None

print(json.dumps({
    'claims_sample': sample(claims if isinstance(claims,list) else []),
    'consumptions_sample': sample(cons if isinstance(cons,list) else []),
    'returns_sample': sample(rets if isinstance(rets,list) else []),
}, indent=2))
