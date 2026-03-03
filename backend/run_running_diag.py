import json
import sqlite3

con = sqlite3.connect('backend.db')
con.row_factory = sqlite3.Row
cur = con.cursor()

running = [
    dict(r)
    for r in cur.execute(
        "SELECT id, mode, status, started_at FROM solver_runs WHERE mode='live' AND status='running' ORDER BY id DESC"
    ).fetchall()
]
print('RUNNING_LIVE', json.dumps(running, default=str))

for r in running:
    rid = int(r['id'])
    final_rows = cur.execute('SELECT COUNT(*) c FROM final_demands WHERE solver_run_id=?', (rid,)).fetchone()['c']
    alloc_rows = cur.execute('SELECT COUNT(*) c FROM allocations WHERE solver_run_id=?', (rid,)).fetchone()['c']
    print('RUNNING_COUNTS', rid, final_rows, alloc_rows)

con.close()
