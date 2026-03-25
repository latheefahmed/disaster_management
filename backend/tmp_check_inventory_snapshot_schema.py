import sqlite3, json
conn=sqlite3.connect('backend.db')
cur=conn.cursor()
cur.execute('PRAGMA table_info(inventory_snapshots)')
print(cur.fetchall())
cur.execute("SELECT * FROM inventory_snapshots WHERE solver_run_id=1132 AND resource_id IN ('R39','R5','R6','R40') LIMIT 20")
rows=cur.fetchall()
print('ROWS', rows[:5], 'COUNT', len(rows))
conn.close()
