import sqlite3, json
conn = sqlite3.connect('backend.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("""
SELECT id, status, mode, started_at
FROM solver_runs
ORDER BY id DESC
LIMIT 20
""")
runs = [dict(r) for r in cur.fetchall()]
print('LAST_20_RUNS', json.dumps(runs, default=str))

cur.execute("""
SELECT solver_run_id, COALESCE(allocation_source_scope, supply_level, 'unknown') AS source_scope,
       COUNT(*) AS rows, ROUND(SUM(COALESCE(allocated_quantity,0)),3) AS qty
FROM allocations
WHERE solver_run_id IN (SELECT id FROM solver_runs ORDER BY id DESC LIMIT 10)
GROUP BY solver_run_id, source_scope
ORDER BY solver_run_id DESC, qty DESC
""")
rows = [dict(r) for r in cur.fetchall()]
print('LAST_10_SOURCE_BREAKDOWN', json.dumps(rows, default=str))

cur.execute("""
SELECT COALESCE(allocation_source_scope, supply_level, 'unknown') AS source_scope,
       COUNT(*) AS rows, ROUND(SUM(COALESCE(allocated_quantity,0)),3) AS qty
FROM allocations
WHERE solver_run_id IN (SELECT id FROM solver_runs ORDER BY id DESC LIMIT 30)
GROUP BY source_scope
ORDER BY qty DESC
""")
agg = [dict(r) for r in cur.fetchall()]
print('LAST_30_AGG', json.dumps(agg, default=str))

conn.close()
