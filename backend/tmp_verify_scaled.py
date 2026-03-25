import sqlite3
con = sqlite3.connect('backend.db')
cur = con.cursor()
print('LATEST_RUN', cur.execute("select id from solver_runs where status='completed' and mode='live' order by id desc limit 1").fetchone())
print('RUN1097_R39_ALLOC', cur.execute("select count(1), coalesce(sum(allocated_quantity),0) from allocations where district_code='603' and solver_run_id=1097 and resource_id='R39' and is_unmet=0").fetchone())
print('TOP_RUN1097_D603', cur.execute("select resource_id, sum(allocated_quantity) qty from allocations where district_code='603' and solver_run_id=1097 and is_unmet=0 group by resource_id order by qty desc limit 12").fetchall())
print('KPI_SUMMARY_100', cur.execute("select coalesce(sum(demand_quantity),0) from final_demands where solver_run_id in (select id from solver_runs where status='completed' and mode='live' order by id desc limit 100)").fetchone())
