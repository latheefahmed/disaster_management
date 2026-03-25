import requests, json
BASE='http://127.0.0.1:8000'

def login(u,p):
    r=requests.post(f'{BASE}/auth/login', json={'username':u,'password':p}, timeout=30)
    r.raise_for_status()
    return r.json()['access_token']

t=login('national_admin','national123')
h={'Authorization': f'Bearer {t}'}
resp=requests.get(f'{BASE}/admin/scenarios/405/runs/1177/summary', headers=h, timeout=60)
print('STATUS', resp.status_code)
body=resp.json()
esc=body.get('escalation_status') or {}
print(json.dumps({
  'mode': esc.get('mode'),
  'events_found': esc.get('events_found'),
  'state_marked': esc.get('state_marked'),
  'national_marked': esc.get('national_marked'),
  'neighbor_offers_created': esc.get('neighbor_offers_created'),
  'neighbor_offers_accepted': esc.get('neighbor_offers_accepted'),
  'neighbor_accepted_quantity': esc.get('neighbor_accepted_quantity'),
  'used_state_stock': body.get('used_state_stock'),
  'used_national_stock': body.get('used_national_stock'),
  'source_scope_breakdown': (body.get('source_scope_breakdown') or {}).get('allocations'),
  'totals': body.get('totals'),
}, indent=2))
