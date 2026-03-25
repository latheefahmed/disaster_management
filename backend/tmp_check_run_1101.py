import sqlite3

conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()

run = cur.execute('select id, mode, status, started_at from solver_runs where id=?',(1101,)).fetchone()
print('RUN1101', dict(run) if run else None)
rows = cur.execute('''
select id, solver_run_id, resource_id, time, allocated_quantity, supply_level,
       allocation_source_scope, origin_state_code, state_code, district_code, is_unmet
from allocations
where solver_run_id=?
order by id
''',(1101,)).fetchall()
print('ALLOC1101_COUNT', len(rows))
for r in rows:
    print(dict(r))

conn.close()
