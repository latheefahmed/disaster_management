import sqlite3, json
conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()

# post-rollback source usage in last 10 runs
cur.execute("""
SELECT solver_run_id, COALESCE(allocation_source_scope, supply_level, 'unknown') AS source_scope,
       COUNT(*) AS rows, ROUND(SUM(COALESCE(allocated_quantity,0)),3) AS qty
FROM allocations
WHERE solver_run_id IN (SELECT id FROM solver_runs ORDER BY id DESC LIMIT 10)
GROUP BY solver_run_id, source_scope
ORDER BY solver_run_id DESC, qty DESC
""")
print('LAST_10_SOURCE_BREAKDOWN', json.dumps([dict(r) for r in cur.fetchall()]))

# interstate evidence: state allocations supplied from a different state than request state
cur.execute("""
SELECT solver_run_id,
       COUNT(*) AS interstate_rows,
       ROUND(SUM(COALESCE(allocated_quantity,0)),3) AS interstate_qty
FROM allocations
WHERE solver_run_id IN (SELECT id FROM solver_runs ORDER BY id DESC LIMIT 10)
  AND LOWER(COALESCE(allocation_source_scope, supply_level, ''))='state'
  AND COALESCE(origin_state_code,'') <> ''
  AND COALESCE(state_code,'') <> ''
  AND origin_state_code <> state_code
GROUP BY solver_run_id
ORDER BY solver_run_id DESC
""")
print('LAST_10_INTERSTATE_STATE_ROWS', json.dumps([dict(r) for r in cur.fetchall()]))

# verify rollback touched only non-last10 rows by checking returned=allocated for older runs
cur.execute("""
SELECT COUNT(*) AS older_full_return_rows
FROM allocations
WHERE COALESCE(is_unmet,0)=0
  AND COALESCE(solver_run_id,0) NOT IN (SELECT id FROM solver_runs ORDER BY id DESC LIMIT 10)
  AND ABS(COALESCE(returned_quantity,0)-COALESCE(allocated_quantity,0)) <= 1e-9
  AND COALESCE(allocated_quantity,0) > 0
""")
print('OLDER_FULL_RETURN_ROWS', cur.fetchone()['older_full_return_rows'])

cur.execute("""
SELECT COUNT(*) AS last10_full_return_rows
FROM allocations
WHERE COALESCE(is_unmet,0)=0
  AND COALESCE(solver_run_id,0) IN (SELECT id FROM solver_runs ORDER BY id DESC LIMIT 10)
  AND ABS(COALESCE(returned_quantity,0)-COALESCE(allocated_quantity,0)) <= 1e-9
  AND COALESCE(allocated_quantity,0) > 0
""")
print('LAST10_FULL_RETURN_ROWS', cur.fetchone()['last10_full_return_rows'])

conn.close()
