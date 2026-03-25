import sqlite3
conn=sqlite3.connect('backend.db')
cur=conn.cursor()
for rid in (1102,1103,1104):
    run=cur.execute('select id,mode,status,started_at from solver_runs where id=?',(rid,)).fetchone()
    alloc=cur.execute("select coalesce(supply_level,'district'), count(*), coalesce(sum(allocated_quantity),0) from allocations where solver_run_id=? and coalesce(is_unmet,0)=0 group by coalesce(supply_level,'district')",(rid,)).fetchall()
    unmet=cur.execute("select count(*), coalesce(sum(allocated_quantity),0) from allocations where solver_run_id=? and coalesce(is_unmet,0)=1",(rid,)).fetchone()
    print('RUN',rid,run,'ALLOC',alloc,'UNMET',unmet)
conn.close()
