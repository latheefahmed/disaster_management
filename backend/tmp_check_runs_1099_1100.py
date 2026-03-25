import sqlite3
conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()
for rid in (1099,1100):
    row=cur.execute("select id,status,mode,scenario_id,started_at,completed_at,summary_snapshot_json from solver_runs where id=?",(rid,)).fetchone()
    print('RUN',rid, dict(row) if row else None)
conn.close()
