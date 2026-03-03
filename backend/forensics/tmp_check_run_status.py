import json
import sqlite3

c = sqlite3.connect('backend.db')
c.row_factory = sqlite3.Row
cur = c.cursor()

runs = cur.execute("SELECT id, mode, status FROM solver_runs ORDER BY id DESC LIMIT 5").fetchall()
out = []
for r in runs:
    rid = int(r["id"])
    alloc = int(cur.execute("SELECT COUNT(1) c FROM allocations WHERE solver_run_id=?", (rid,)).fetchone()["c"])
    unmet = float(cur.execute("SELECT COALESCE(SUM(allocated_quantity),0) s FROM allocations WHERE solver_run_id=? AND COALESCE(is_unmet,0)=1", (rid,)).fetchone()["s"] or 0.0)
    dalloc = float(cur.execute("SELECT COALESCE(SUM(allocated_quantity),0) s FROM allocations WHERE solver_run_id=? AND district_code='603' AND COALESCE(is_unmet,0)=0", (rid,)).fetchone()["s"] or 0.0)
    dunmet = float(cur.execute("SELECT COALESCE(SUM(allocated_quantity),0) s FROM allocations WHERE solver_run_id=? AND district_code='603' AND COALESCE(is_unmet,0)=1", (rid,)).fetchone()["s"] or 0.0)
    out.append({
        "run_id": rid,
        "mode": str(r["mode"]),
        "status": str(r["status"]),
        "alloc_rows": alloc,
        "unmet_total": unmet,
        "district603_allocated": dalloc,
        "district603_unmet": dunmet,
    })

print(json.dumps(out, indent=2))
c.close()
