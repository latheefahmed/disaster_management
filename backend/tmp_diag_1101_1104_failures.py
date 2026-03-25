import sqlite3, json
conn=sqlite3.connect('backend.db')
conn.row_factory=sqlite3.Row
cur=conn.cursor()
for rid in (1101,1102,1103,1104):
    run=cur.execute('select id,mode,status,started_at,summary_snapshot_json from solver_runs where id=?',(rid,)).fetchone()
    if not run:
        print('RUN',rid,'MISSING'); continue
    summ = run['summary_snapshot_json']
    parsed = None
    try:
        parsed = json.loads(summ) if summ else None
    except Exception:
        parsed = None
    print('\nRUN',rid, {'status':run['status'],'started_at':run['started_at'],'has_summary':bool(parsed)})
    if parsed:
        totals = parsed.get('totals') or {}
        esc = parsed.get('escalation_status') or {}
        scope = (parsed.get('source_scope_breakdown') or {}).get('allocations') or {}
        print('TOTALS', totals)
        print('SCOPE', scope)
        print('ESC', esc)
    unmet=cur.execute('select count(*), coalesce(sum(allocated_quantity),0) from allocations where solver_run_id=? and coalesce(is_unmet,0)=1',(rid,)).fetchone()
    print('UNMET_ROWS_QTY', tuple(unmet))

# audit hints
if cur.execute("select count(*) from sqlite_master where type='table' and name='audit_logs'").fetchone()[0]:
    rows=cur.execute("""
    select id, event_type, payload_json, created_at
    from audit_logs
    where payload_json like '%1103%' or payload_json like '%1104%'
    order by id desc limit 20
    """).fetchall()
    print('\nAUDIT_MATCHES',len(rows))
    for r in rows[:10]:
        print(dict(r))
conn.close()
