import json, sqlite3
r = json.load(open('REALWORLD_SCALE_REPORT.json'))
print('R39_FACTOR', r['resource_factors'].get('R39'))
con = sqlite3.connect('backend.db')
cur = con.cursor()
print('RUN1097_R39_ALLOC', cur.execute("select count(1), coalesce(sum(allocated_quantity),0) from allocations where district_code='603' and solver_run_id=1097 and resource_id='R39' and is_unmet=0").fetchone())
print('TOP_RUN1097_D603', cur.execute("select resource_id, sum(allocated_quantity) qty from allocations where district_code='603' and solver_run_id=1097 and is_unmet=0 group by resource_id order by qty desc limit 12").fetchall())
