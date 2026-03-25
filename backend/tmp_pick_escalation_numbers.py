import sqlite3
from collections import defaultdict

con = sqlite3.connect('backend.db')
cur = con.cursor()

state_code = cur.execute("select state_code from districts where district_code='603'").fetchone()
state_code = str(state_code[0]) if state_code else None
latest_run = cur.execute("select id from solver_runs where status='completed' and mode='live' order by id desc limit 1").fetchone()
latest_run = int(latest_run[0]) if latest_run else None

d_stock = {}
if latest_run is not None:
    rows = cur.execute("""
      select resource_id, coalesce(sum(quantity),0)
      from inventory_snapshots
      where district_code='603' and solver_run_id=?
      group by resource_id
    """, (latest_run,)).fetchall()
    d_stock = {r: float(q or 0) for r, q in rows}

s_stock = defaultdict(float)
n_stock = defaultdict(float)
for scope, sc, rid, q in cur.execute("""
  select lower(coalesce(scope,'')), coalesce(state_code,''), resource_id, coalesce(sum(quantity_delta),0)
  from stock_refill_transactions
  group by lower(coalesce(scope,'')), coalesce(state_code,''), resource_id
""").fetchall():
    scope = str(scope)
    rid = str(rid)
    qty = float(q or 0)
    if scope == 'state' and str(sc) == str(state_code):
        s_stock[rid] += qty
    elif scope == 'national':
        n_stock[rid] += qty

other_state_stock = defaultdict(float)
for sc, rid, q in cur.execute("""
  select coalesce(state_code,''), resource_id, coalesce(sum(quantity_delta),0)
  from stock_refill_transactions
  where lower(coalesce(scope,''))='state'
  group by coalesce(state_code,''), resource_id
""").fetchall():
    sc = str(sc)
    if sc != str(state_code):
        other_state_stock[str(rid)] += float(q or 0)

resources = set(d_stock) | set(s_stock) | set(n_stock) | set(other_state_stock)
candidates = []
for rid in resources:
    d = max(0.0, d_stock.get(rid, 0.0))
    s = max(0.0, s_stock.get(rid, 0.0))
    n = max(0.0, n_stock.get(rid, 0.0))
    o = max(0.0, other_state_stock.get(rid, 0.0))
    candidates.append((rid, d, s, n, o))

state_pick = None
for rid, d, s, n, o in sorted(candidates, key=lambda x: (x[2], x[1]), reverse=True):
    if s > 1:
        q = int(d + min(s, max(2, s*0.25)))
        if q > d and q <= d + s:
            state_pick = (rid, d, s, n, o, q)
            break

national_pick = None
for rid, d, s, n, o in sorted(candidates, key=lambda x: (x[3], x[2], x[1]), reverse=True):
    if n > 1:
        q = int(d + s + min(n, max(2, n*0.25)))
        if q > d + s and q <= d + s + n:
            national_pick = (rid, d, s, n, o, q)
            break

inter_pick = None
for rid, d, s, n, o in sorted(candidates, key=lambda x: (x[4], -x[2], x[1]), reverse=True):
    if o > 5 and s < max(1.0, o*0.2):
        q = int(d + s + min(o, max(2, o*0.15)))
        inter_pick = (rid, d, s, n, o, q)
        break

name_map = {r: n for r, n in cur.execute("select resource_id, resource_name from resources").fetchall()}

def fmt(p):
    if not p:
        return None
    rid, d, s, n, o, q = p
    return {
      'resource_id': rid,
      'resource_name': name_map.get(rid, rid),
      'district_603_stock': round(d, 3),
      'own_state_stock': round(s, 3),
      'national_stock': round(n, 3),
      'other_states_stock': round(o, 3),
      'request_quantity_to_test': q,
      'time_index': 0,
      'latest_run': latest_run,
      'district': '603',
      'state_code': state_code,
    }

print({'state_scenario': fmt(state_pick), 'national_scenario': fmt(national_pick), 'inter_state_scenario': fmt(inter_pick)})
