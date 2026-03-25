import sqlite3
conn=sqlite3.connect('backend.db')
cur=conn.cursor()
print('SOLVER_RUNS_COLS', cur.execute('pragma table_info(solver_runs)').fetchall())
for rid in (1099,1100):
    row=cur.execute('select * from solver_runs where id=?',(rid,)).fetchone()
    print('RUN', rid, row)
conn.close()
