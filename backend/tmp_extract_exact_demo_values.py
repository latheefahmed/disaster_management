import sqlite3
from collections import defaultdict

DB_PATH = r"C:/Users/LATHEEF/Desktop/disaster_management/backend/backend.db"

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cur = con.cursor()

# latest completed run
cur.execute("SELECT id FROM solver_runs WHERE status='completed' ORDER BY id DESC LIMIT 1")
row = cur.fetchone()
if not row:
    print("NO_COMPLETED_RUN")
    raise SystemExit(0)
run_id = int(row[0])

# district -> state map
cur.execute("SELECT district_code, state_code FROM districts")
district_to_state = {str(r[0]): str(r[1]) for r in cur.fetchall()}

# district stock from latest completed run snapshots
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
district_stock = {}
for r in cur.fetchall():
    key = (str(r["district_code"]), str(r["resource_id"]), int(r["time"]))
    district_stock[key] = float(r["qty"])

# state pool by resource/time
cur.execute(
    """
    SELECT state_code, resource_id, time, SUM(quantity_delta) AS qty
    FROM pool_transactions
    GROUP BY state_code, resource_id, time
    HAVING SUM(quantity_delta) > 0
    """
)
state_pool = {}
for r in cur.fetchall():
    key = (str(r["state_code"]), str(r["resource_id"]), int(r["time"]))
    state_pool[key] = float(r["qty"])

# national/global pool by resource/time
cur.execute(
    """
    SELECT resource_id, time, SUM(quantity_delta) AS qty
    FROM pool_transactions
    GROUP BY resource_id, time
    HAVING SUM(quantity_delta) > 0
    """
)
national_pool = {}
for r in cur.fetchall():
    key = (str(r["resource_id"]), int(r["time"]))
    national_pool[key] = float(r["qty"])

# candidate tuples where all three layers exist
candidates = []
for (district_code, resource_id, t), d_qty in district_stock.items():
    state_code = district_to_state.get(district_code)
    if not state_code:
        continue
    s_qty = state_pool.get((state_code, resource_id, t), 0.0)
    n_qty = national_pool.get((resource_id, t), 0.0)
    if d_qty > 0 and s_qty > 0 and n_qty > 0:
        total = d_qty + s_qty + n_qty
        candidates.append((total, district_code, state_code, resource_id, t, d_qty, s_qty, n_qty))

candidates.sort(reverse=True)
print(f"LATEST_COMPLETED_RUN={run_id}")
print(f"CANDIDATES_WITH_D_S_N={len(candidates)}")

for idx, c in enumerate(candidates[:12], start=1):
    total, district_code, state_code, resource_id, t, d_qty, s_qty, n_qty = c
    q1 = round(0.30 * d_qty, 2)
    q2 = round(1.10 * d_qty, 2)
    q3 = round(d_qty + 0.60 * s_qty, 2)
    q4 = round(d_qty + s_qty + 0.40 * n_qty, 2)
    q5 = round(d_qty + s_qty + n_qty + 0.50 * n_qty, 2)
    print(f"#{idx} district={district_code} state={state_code} resource={resource_id} time={t}")
    print(f"   D={d_qty:.2f} S={s_qty:.2f} N={n_qty:.2f} TOTAL={total:.2f}")
    print(f"   Q1={q1} Q2={q2} Q3={q3} Q4={q4} Q5={q5}")

# also print top district-only stock for fallback
print("TOP_DISTRICT_STOCK:")
for idx, ((district_code, resource_id, t), d_qty) in enumerate(sorted(district_stock.items(), key=lambda kv: kv[1], reverse=True)[:8], start=1):
    print(f"  {idx}. district={district_code} resource={resource_id} time={t} D={d_qty:.2f} state={district_to_state.get(district_code, '?')}")
