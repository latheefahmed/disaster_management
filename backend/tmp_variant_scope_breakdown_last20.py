import json, sqlite3
from pathlib import Path
rep=json.loads(Path('LIVE_AUTO_ESCALATION_20_OPTIMAL_REPORT.json').read_text(encoding='utf-8'))
req_variant={}
run_ids=[]
for w in rep.get('waves',[]):
    run_ids.append(int(w.get('run_id') or 0))
    for rr in w.get('request_rows',[]):
        rid=int(rr.get('request_id') or 0)
        if rid>0:
            req_variant[rid]=rr.get('variant')

conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()
rows=cur.execute(f"select request_id, coalesce(allocation_source_scope,supply_level,'district') as scope, coalesce(sum(allocated_quantity),0) qty from allocations where solver_run_id in ({','.join(str(r) for r in run_ids if r)}) and coalesce(is_unmet,0)=0 and request_id>0 group by request_id, coalesce(allocation_source_scope,supply_level,'district') order by request_id").fetchall()
by_variant={}
for r in rows:
    req_id=int(r['request_id'])
    v=req_variant.get(req_id,'unknown')
    by_variant.setdefault(v, {'district':0.0,'state':0.0,'neighbor_state':0.0,'national':0.0})
    k=str(r['scope']).lower()
    if k not in by_variant[v]: k='district'
    by_variant[v][k]+=float(r['qty'] or 0.0)
print('RUN_IDS',run_ids)
print('BY_VARIANT',by_variant)
conn.close()
