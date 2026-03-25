import sqlite3, json
conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()
req_ids=(3381,3382,3383,3384,3385)
ph=','.join('?'*len(req_ids))

cur.execute(f"""
SELECT id, solver_run_id, request_id, source_request_id, resource_id,
       allocation_source_scope, supply_level, state_code, origin_state_code,
       allocated_quantity
FROM allocations
WHERE solver_run_id=1131
  AND (request_id IN ({ph}) OR source_request_id IN ({ph}))
ORDER BY id
""", req_ids+req_ids)
rows=[dict(r) for r in cur.fetchall()]
print('MATCH_ROWS', len(rows))
print(json.dumps(rows, indent=2))

cur.execute("""
SELECT allocation_source_scope, COUNT(*), ROUND(SUM(allocated_quantity),3)
FROM allocations
WHERE solver_run_id=1131 AND COALESCE(is_unmet,0)=0
GROUP BY allocation_source_scope
""")
print('RUN1131_SCOPE', cur.fetchall())
conn.close()
