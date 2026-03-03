import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "backend.db"

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cur = con.cursor()

cols = [r["name"] for r in cur.execute("PRAGMA table_info(solver_runs)").fetchall()]
ts_col = "created_at" if "created_at" in cols else ("started_at" if "started_at" in cols else "id")

print("timestamp_column", ts_col)

rows = [
    dict(r)
    for r in cur.execute(
        f"SELECT id, mode, status, {ts_col} AS run_time FROM solver_runs ORDER BY id DESC LIMIT 10"
    ).fetchall()
]
print("A", json.dumps(rows, default=str))

latest = cur.execute(
    "SELECT id FROM solver_runs WHERE mode='live' AND status='completed' ORDER BY id DESC LIMIT 1"
).fetchone()
latest_id = latest["id"] if latest else None
print("B_latest_completed_live_run_id", latest_id)

if latest_id is None:
    print("C_final_demands_count", None)
    print("D_allocations_count", None)
    print("E_unmet_count", None)
    print("F_slots", json.dumps([]))
else:
    c = cur.execute("SELECT COUNT(*) c FROM final_demands WHERE solver_run_id=?", (latest_id,)).fetchone()["c"]
    d = cur.execute("SELECT COUNT(*) c FROM allocations WHERE solver_run_id=?", (latest_id,)).fetchone()["c"]
    e = cur.execute("SELECT COUNT(*) c FROM allocations WHERE solver_run_id=? AND is_unmet=1", (latest_id,)).fetchone()["c"]
    print("C_final_demands_count", c)
    print("D_allocations_count", d)
    print("E_unmet_count", e)

    slots = [
        dict(r)
        for r in cur.execute(
            """
            SELECT district_code, resource_id, time,
                   SUM(CASE WHEN is_unmet=0 THEN allocated_quantity ELSE 0 END) AS alloc,
                   SUM(CASE WHEN is_unmet=1 THEN allocated_quantity ELSE 0 END) AS unmet
            FROM allocations
            WHERE solver_run_id=?
            GROUP BY district_code, resource_id, time
            LIMIT 20
            """,
            (latest_id,),
        ).fetchall()
    ]
    print("F_slots", json.dumps(slots, default=str))

con.close()
