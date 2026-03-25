import sqlite3
from collections import defaultdict

DB_PATH = r"C:/Users/LATHEEF/Desktop/disaster_management/backend/backend.db"

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cur = con.cursor()

# Latest completed run for district stock snapshot
cur.execute("SELECT id FROM solver_runs WHERE status='completed' ORDER BY id DESC LIMIT 1")
run_row = cur.fetchone()
if not run_row:
    print("NO_COMPLETED_RUN")
    raise SystemExit(0)
run_id = int(run_row[0])

# district -> state
cur.execute("SELECT district_code, state_code FROM districts")
d2s = {str(r[0]): str(r[1]) for r in cur.fetchall()}

# district stock by district/resource/time from latest run
cur.execute(
    """
    SELECT district_code, resource_id, time, SUM(quantity) AS qty
    FROM inventory_snapshots
    WHERE solver_run_id = ?
    GROUP BY district_code, resource_id, time
    HAVING SUM(quantity) > 0
    """,
    (run_id,),
)
d_stock = {(str(r["district_code"]), str(r["resource_id"]), int(r["time"])): float(r["qty"]) for r in cur.fetchall()}

# refill maps (net) per scope, excluding scenario solver debits can be tricky; here we use raw net from table
cur.execute(
    """
    SELECT scope, district_code, state_code, resource_id, SUM(quantity_delta) AS qty
    FROM stock_refill_transactions
    GROUP BY scope, district_code, state_code, resource_id
    """
)
state_map = defaultdict(float)
national_map = defaultdict(float)
for r in cur.fetchall():
    scope = str(r["scope"])
    rid = str(r["resource_id"])
    qty = float(r["qty"] or 0.0)
    if scope == "state" and r["state_code"]:
        state_map[(str(r["state_code"]), rid)] += qty
    elif scope == "national":
        national_map[rid] += qty

# keep only positive usable balances
state_map = {k: v for k, v in state_map.items() if v > 0}
national_map = {k: v for k, v in national_map.items() if v > 0}

print(f"LATEST_COMPLETED_RUN={run_id}")
print(f"POSITIVE_STATE_STOCK_KEYS={len(state_map)}")
print(f"POSITIVE_NATIONAL_STOCK_KEYS={len(national_map)}")

# find best candidates with D,S,N all positive for same district/resource/time
candidates = []
for (d, rid, t), D in d_stock.items():
    state = d2s.get(d)
    if not state:
        continue
    S = state_map.get((state, rid), 0.0)
    N = national_map.get(rid, 0.0)
    if D > 0 and S > 0 and N > 0:
        score = D + S + N
        candidates.append((score, d, state, rid, t, D, S, N))

candidates.sort(reverse=True)
print(f"CANDIDATES_D_S_N={len(candidates)}")

for i, c in enumerate(candidates[:12], 1):
    score, d, s, rid, t, D, S, N = c
    q1 = round(0.30 * D, 2)
    q2 = round(1.10 * D, 2)
    q3 = round(D + 0.60 * S, 2)
    q4 = round(D + S + 0.40 * N, 2)
    q5 = round(D + S + N + 0.50 * N, 2)
    print(f"#{i} district={d} state={s} resource={rid} time={t}")
    print(f"   D={D:.2f} S={S:.2f} N={N:.2f}")
    print(f"   Q1={q1} Q2={q2} Q3={q3} Q4={q4} Q5={q5}")

print("TOP_STATE_STOCK:")
for i, ((s, rid), qty) in enumerate(sorted(state_map.items(), key=lambda kv: kv[1], reverse=True)[:10], 1):
    print(f"  {i}. state={s} resource={rid} S={qty:.2f}")

print("TOP_NATIONAL_STOCK:")
for i, (rid, qty) in enumerate(sorted(national_map.items(), key=lambda kv: kv[1], reverse=True)[:10], 1):
    print(f"  {i}. resource={rid} N={qty:.2f}")
