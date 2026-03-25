import sqlite3
conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()
run_id=1100
rid='R38'
district='603'
state='33'

def q(sql, p):
    v=cur.execute(sql,p).fetchone()
    return None if not v else v[0]

inv_d=q("select sum(quantity) from inventory_snapshots where solver_run_id=? and district_code=? and resource_id=?",(run_id,district,rid))
inv_state_total=q("select sum(quantity) from scenario_state_stock where scenario_id=(select scenario_id from solver_runs where id=?) and state_code=? and resource_id=?",(run_id,state,rid))
inv_national=q("select sum(quantity) from scenario_national_stock where scenario_id=(select scenario_id from solver_runs where id=?) and resource_id=?",(run_id,rid))

state_alloc_same_run=q("select sum(allocated_quantity) from allocations where solver_run_id=? and resource_id=? and state_code=? and coalesce(is_unmet,0)=0 and lower(coalesce(supply_level,'district'))='state'",(run_id,rid,state))
nat_alloc_same_run=q("select sum(allocated_quantity) from allocations where solver_run_id=? and resource_id=? and coalesce(is_unmet,0)=0 and lower(coalesce(supply_level,'district'))='national'",(run_id,rid))

print({'run_id':run_id,'rid':rid,'district_stock_snapshot':inv_d,'state_stock_snapshot':inv_state_total,'national_stock_snapshot':inv_national,'state_alloc_same_run':state_alloc_same_run,'national_alloc_same_run':nat_alloc_same_run})
conn.close()
