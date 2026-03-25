import sqlite3
conn = sqlite3.connect('backend.db')
cur = conn.cursor()
for t in ['solver_runs','allocations']:
    cur.execute(f"PRAGMA table_info({t})")
    print(t, [r[1] for r in cur.fetchall()])
conn.close()
