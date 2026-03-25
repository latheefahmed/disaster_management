import requests, json
BASE='http://127.0.0.1:8000'

def login(u,p):
    r=requests.post(f'{BASE}/auth/login',json={'username':u,'password':p},timeout=20)
    r.raise_for_status()
    return r.json()['access_token']

t=login('district_603','district123')
r=requests.get(f'{BASE}/district/stock',headers={'Authorization':f'Bearer {t}'},timeout=30)
print('STATUS',r.status_code,'ROWS',len(r.json() if r.headers.get('content-type','').startswith('application/json') else []))
