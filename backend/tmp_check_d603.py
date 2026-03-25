import sqlite3
con = sqlite3.connect('backend.db')
cur = con.cursor()
print('LATEST_RUN', cur.execute("select id from solver_runs where status='completed' and mode='live' order by id desc limit 1").fetchone())
print('D603_RUN1097_DIESEL_ALLOC', cur.execute("select count(1), coalesce(sum(allocated_quantity),0) from allocations where district_code='603' and solver_run_id=1097 and is_unmet=0 and resource_id='diesel_liters'").fetchone())
print('D603_RUN1097_TOP_RES', cur.execute("select resource_id, count(1), sum(allocated_quantity) qty from allocations where district_code='603' and solver_run_id=1097 and is_unmet=0 group by resource_id order by qty desc limit 15").fetchall())
