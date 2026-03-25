import sqlite3
conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()
run_id=1100
rid='R38'
d='603'; s='33'
print('inv run1100 d603 r38', cur.execute('select count(*), coalesce(sum(quantity),0) from inventory_snapshots where solver_run_id=? and district_code=? and resource_id=?',(run_id,d,rid)).fetchone())
print('inv run1099 d603 r38', cur.execute('select count(*), coalesce(sum(quantity),0) from inventory_snapshots where solver_run_id=? and district_code=? and resource_id=?',(1099,d,rid)).fetchone())
print('state stock scenario from run1100', cur.execute('select scenario_id from solver_runs where id=?',(run_id,)).fetchone())
print('scenario_state_stock rows for rid', cur.execute('select count(*), coalesce(sum(quantity),0) from scenario_state_stock where scenario_id=(select scenario_id from solver_runs where id=?) and state_code=? and resource_id=?',(run_id,s,rid)).fetchone())
print('scenario_national_stock rows for rid', cur.execute('select count(*), coalesce(sum(quantity),0) from scenario_national_stock where scenario_id=(select scenario_id from solver_runs where id=?) and resource_id=?',(run_id,rid)).fetchone())
print('alloc by scope run1100 rid', cur.execute("select coalesce(supply_level,'district'), count(*), coalesce(sum(allocated_quantity),0) from allocations where solver_run_id=? and resource_id=? and coalesce(is_unmet,0)=0 group by coalesce(supply_level,'district')",(run_id,rid)).fetchall())
conn.close()
