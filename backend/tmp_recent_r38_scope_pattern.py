import sqlite3
conn=sqlite3.connect('backend.db')
cur=conn.cursor()
rid='R38'; state='33'; d='603'
print('state stock base csv row? (derived through current run snapshot proxy)')
print('latest run with nonzero d603 r38', cur.execute("select solver_run_id, sum(quantity) from inventory_snapshots where district_code=? and resource_id=? group by solver_run_id having sum(quantity)>0 order by solver_run_id desc limit 5",(d,rid)).fetchall())
print('latest run with zero d603 r38', cur.execute("select solver_run_id, sum(quantity) from inventory_snapshots where district_code=? and resource_id=? group by solver_run_id order by solver_run_id desc limit 5",(d,rid)).fetchall())
print('state-scope allocations recent for r38', cur.execute("select solver_run_id, sum(allocated_quantity) from allocations where resource_id=? and coalesce(is_unmet,0)=0 and lower(coalesce(supply_level,'district'))='state' and state_code=? group by solver_run_id order by solver_run_id desc limit 10",(rid,state)).fetchall())
print('national-scope allocations recent for r38', cur.execute("select solver_run_id, sum(allocated_quantity) from allocations where resource_id=? and coalesce(is_unmet,0)=0 and lower(coalesce(supply_level,'district'))='national' group by solver_run_id order by solver_run_id desc limit 10",(rid,)).fetchall())
conn.close()
