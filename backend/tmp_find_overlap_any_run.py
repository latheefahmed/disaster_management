import sqlite3
from collections import defaultdict

DB_PATH = r"C:/Users/LATHEEF/Desktop/disaster_management/backend/backend.db"
con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cur = con.cursor()

# district->state
cur.execute("SELECT district_code, state_code FROM districts")
d2s = {str(r[0]): str(r[1]) for r in cur.fetchall()}

# latest completed inventory per district/resource/time across all runs
cur.execute(
    """
    WITH latest AS (
      SELECT i.district_code, i.resource_id, i.time, MAX(i.solver_run_id) AS max_run_id
      FROM inventory_snapshots i
      JOIN solver_runs s ON s.id = i.solver_run_id
      WHERE s.status = 'completed'
      GROUP BY i.district_code, i.resource_id, i.time
    )
    SELECT i.district_code, i.resource_id, i.time, SUM(i.quantity) AS qty
    FROM inventory_snapshots i
    JOIN latest l
      ON l.district_code=i.district_code
     AND l.resource_id=i.resource_id
     AND l.time=i.time
     AND l.max_run_id=i.solver_run_id
    GROUP BY i.district_code, i.resource_id, i.time
    HAVING SUM(i.quantity) > 0
    """
)
d_stock = {(str(r['district_code']), str(r['resource_id']), int(r['time'])): float(r['qty']) for r in cur.fetchall()}

# state / national stock from refill transactions net
cur.execute(
    """
    SELECT scope, state_code, resource_id, SUM(quantity_delta) AS qty
    FROM stock_refill_transactions
    GROUP BY scope, state_code, resource_id
    """
)
state_map = defaultdict(float)
national_map = defaultdict(float)
for r in cur.fetchall():
    scope = str(r['scope'])
    rid = str(r['resource_id'])
    qty = float(r['qty'] or 0.0)
    if scope == 'state' and r['state_code']:
        state_map[(str(r['state_code']), rid)] += qty
    elif scope == 'national':
        national_map[rid] += qty
state_map = {k:v for k,v in state_map.items() if v > 0}
national_map = {k:v for k,v in national_map.items() if v > 0}

# candidates D+S+N with same resource
cand_dsn = []
cand_ds = []
cand_dn = []
for (d, rid, t), D in d_stock.items():
    s = d2s.get(d)
    if not s:
        continue
    S = state_map.get((s, rid), 0.0)
    N = national_map.get(rid, 0.0)
    if D > 0 and S > 0 and N > 0:
        cand_dsn.append((D+S+N, d,s,rid,t,D,S,N))
    if D > 0 and S > 0:
        cand_ds.append((D+S, d,s,rid,t,D,S))
    if D > 0 and N > 0:
        cand_dn.append((D+N, d,s,rid,t,D,N))

cand_dsn.sort(reverse=True)
cand_ds.sort(reverse=True)
cand_dn.sort(reverse=True)

print(f"D_STOCK_KEYS={len(d_stock)}")
print(f"STATE_KEYS={len(state_map)} NATIONAL_KEYS={len(national_map)}")
print(f"CAND_DSN={len(cand_dsn)} CAND_DS={len(cand_ds)} CAND_DN={len(cand_dn)}")

print('TOP_DSN:')
for i,c in enumerate(cand_dsn[:10],1):
    _,d,s,rid,t,D,S,N=c
    print(f"  {i}. d={d} s={s} rid={rid} t={t} D={D:.2f} S={S:.2f} N={N:.2f}")

print('TOP_DS:')
for i,c in enumerate(cand_ds[:12],1):
    _,d,s,rid,t,D,S=c
    print(f"  {i}. d={d} s={s} rid={rid} t={t} D={D:.2f} S={S:.2f}")

print('TOP_DN:')
for i,c in enumerate(cand_dn[:12],1):
    _,d,s,rid,t,D,N=c
    print(f"  {i}. d={d} s={s} rid={rid} t={t} D={D:.2f} N={N:.2f}")
