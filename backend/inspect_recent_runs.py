import json
import sqlite3

con = sqlite3.connect("backend.db")
con.row_factory = sqlite3.Row
cur = con.cursor()

rows = [
    dict(r)
    for r in cur.execute(
        "SELECT id, mode, status, scenario_id, started_at FROM solver_runs ORDER BY id DESC LIMIT 20"
    ).fetchall()
]
print("RECENT_RUNS", json.dumps(rows, default=str, indent=2))

running_live = [
    dict(r)
    for r in cur.execute(
        "SELECT id, mode, status, scenario_id, started_at FROM solver_runs WHERE mode='live' AND status='running' ORDER BY id DESC"
    ).fetchall()
]
print("RUNNING_LIVE", json.dumps(running_live, default=str, indent=2))

fd = [
    tuple(r)
    for r in cur.execute(
        "SELECT solver_run_id, COUNT(*) c FROM final_demands WHERE solver_run_id >= 175 GROUP BY solver_run_id ORDER BY solver_run_id"
    ).fetchall()
]
print("FINAL_DEMAND_COUNTS", fd)

alloc = [
    tuple(r)
    for r in cur.execute(
        "SELECT solver_run_id, COUNT(*) c, SUM(CASE WHEN is_unmet=1 THEN 1 ELSE 0 END) unmet_rows FROM allocations WHERE solver_run_id >= 175 GROUP BY solver_run_id ORDER BY solver_run_id"
    ).fetchall()
]
print("ALLOCATION_COUNTS", alloc)

con.close()
