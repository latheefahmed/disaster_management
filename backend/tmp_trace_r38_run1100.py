import sqlite3, json
conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()
run_id=1100
district='603'
rid='R38'
rows=cur.execute("""
select id,solver_run_id,resource_id,district_code,state_code,time,allocated_quantity,is_unmet,
       supply_level,allocation_source_scope,allocation_source_code,origin_state_code,origin_district_code,
       claimed_quantity,consumed_quantity,returned_quantity,status,request_id,source_request_id
from allocations
where solver_run_id=? and district_code=? and resource_id=?
order by id
""",(run_id,district,rid)).fetchall()
print('ALLOC_ROWS',len(rows))
for r in rows:
    print(dict(r))

reqs=cur.execute("""
select id,request_id,district_code,state_code,resource_id,time,quantity_requested,escalation_level,status,created_at
from requests where id in (select distinct source_request_id from allocations where solver_run_id=? and district_code=? and resource_id=? and source_request_id is not null)
order by id
""",(run_id,district,rid)).fetchall()
print('REQ_ROWS',len(reqs))
for r in reqs:
    print(dict(r))
conn.close()
