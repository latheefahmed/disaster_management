import sqlite3, json
conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()

cur.execute("SELECT id FROM solver_runs ORDER BY id DESC LIMIT 8")
run_ids=[int(r['id']) for r in cur.fetchall()]
print('LATEST_RUN_IDS', run_ids)

ph=','.join('?' for _ in run_ids)
cur.execute(f"""
SELECT solver_run_id,
       COALESCE(allocation_source_scope,'') AS allocation_source_scope,
       COALESCE(supply_level,'') AS supply_level,
       COALESCE(origin_state_code,'') AS origin_state_code,
       COALESCE(state_code,'') AS state_code,
       COUNT(*) AS rows,
       ROUND(SUM(COALESCE(allocated_quantity,0)),3) AS qty
FROM allocations
WHERE solver_run_id IN ({ph})
  AND COALESCE(is_unmet,0)=0
GROUP BY solver_run_id, allocation_source_scope, supply_level, origin_state_code, state_code
ORDER BY solver_run_id DESC, qty DESC
""", tuple(run_ids))
rows=[dict(r) for r in cur.fetchall()]
print('RAW_SCOPE_ROWS', json.dumps(rows))

# targeted interstate indicator for latest 8 runs
cur.execute(f"""
SELECT solver_run_id,
       COUNT(*) AS interstate_rows,
       ROUND(SUM(COALESCE(allocated_quantity,0)),3) AS interstate_qty
FROM allocations
WHERE solver_run_id IN ({ph})
  AND COALESCE(is_unmet,0)=0
  AND LOWER(COALESCE(allocation_source_scope,supply_level,''))='state'
  AND COALESCE(origin_state_code,'') <> ''
  AND COALESCE(state_code,'') <> ''
  AND origin_state_code <> state_code
GROUP BY solver_run_id
ORDER BY solver_run_id DESC
""", tuple(run_ids))
print('INTERSTATE_LATEST8', json.dumps([dict(r) for r in cur.fetchall()]))

conn.close()
