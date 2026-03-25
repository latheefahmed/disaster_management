import sqlite3
conn=sqlite3.connect('backend.db')
cur=conn.cursor()
for t in ['returns','stock_refill_transactions','allocations','solver_runs']:
    cur.execute(f"PRAGMA table_info({t})")
    print('\n',t)
    for r in cur.fetchall():
        print(r)
conn.close()
