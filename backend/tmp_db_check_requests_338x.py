import sqlite3, json
conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()
ids=[3381,3382,3383,3384,3385]
ph=','.join('?'*len(ids))
cur.execute(f"SELECT id,resource_id,quantity,status,created_at FROM requests WHERE id IN ({ph}) ORDER BY id", ids)
print('REQUESTS', json.dumps([dict(r) for r in cur.fetchall()], default=str, indent=2))
cur.execute("SELECT allocation_source_scope as s, COUNT(*) c, ROUND(SUM(allocated_quantity),3) q FROM allocations WHERE solver_run_id=1131 GROUP BY s ORDER BY q DESC")
print('RUN1131_SCOPE', json.dumps([dict(r) for r in cur.fetchall()], indent=2))
conn.close()
