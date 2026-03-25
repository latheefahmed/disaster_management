import json
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "backend.db"
REPORT = ROOT / "RESTORE_POOL_PREVIOUS_RUNS_REPORT.json"


def backup_db() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DB.with_name(f"backend_pre_restore_pool_{stamp}.db")
    shutil.copy2(DB, out)
    return out


def main():
    if not DB.exists():
        raise FileNotFoundError(DB)

    backup = backup_db()

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    latest_live = cur.execute(
        """
        SELECT id FROM solver_runs
        WHERE lower(coalesce(mode,''))='live'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    latest_live_id = int(latest_live[0]) if latest_live else 0

    reason = f"historical_pool_restore_upto_{latest_live_id - 1}" if latest_live_id > 1 else "historical_pool_restore_upto_none"

    cur.execute(
        "DELETE FROM stock_refill_transactions WHERE reason=? AND actor_id='pool_restore'",
        (reason,),
    )

    rows = cur.execute(
        """
        SELECT
            solver_run_id,
            district_code,
            state_code,
            origin_state_code,
            resource_id,
            lower(coalesce(supply_level,'district')) as lvl,
            coalesce(allocated_quantity,0.0) as qty
        FROM allocations
        WHERE coalesce(is_unmet,0)=0
          AND coalesce(allocated_quantity,0) > 0
          AND solver_run_id < ?
        """,
        (latest_live_id,),
    ).fetchall()

    district_group = defaultdict(float)
    state_group = defaultdict(float)
    national_group = defaultdict(float)

    for solver_run_id, district_code, state_code, origin_state_code, resource_id, lvl, qty in rows:
        q = float(qty or 0.0)
        if q <= 0:
            continue
        level = str(lvl or "district")
        rid = str(resource_id)

        if level == "district":
            district_group[(str(district_code or ""), str(state_code or ""), rid)] += q
        elif level == "state":
            origin = str(origin_state_code or state_code or "")
            if origin.upper() == "NATIONAL":
                national_group[rid] += q
            else:
                state_group[(origin, rid)] += q
        elif level == "national":
            national_group[rid] += q
        else:
            district_group[(str(district_code or ""), str(state_code or ""), rid)] += q

    inserts = []
    for (district_code, state_code, rid), qty in district_group.items():
        inserts.append((
            "district", district_code, state_code, rid, float(round(qty, 6)), reason,
            "system", "pool_restore", "manual_refill", None
        ))

    for (state_code, rid), qty in state_group.items():
        inserts.append((
            "state", None, state_code, rid, float(round(qty, 6)), reason,
            "system", "pool_restore", "manual_refill", None
        ))

    for rid, qty in national_group.items():
        inserts.append((
            "national", None, None, rid, float(round(qty, 6)), reason,
            "system", "pool_restore", "manual_refill", None
        ))

    if inserts:
        cur.executemany(
            """
            INSERT INTO stock_refill_transactions (
                scope, district_code, state_code, resource_id,
                quantity_delta, reason, actor_role, actor_id,
                source, solver_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            inserts,
        )

    conn.commit()

    payload = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "db": str(DB),
        "backup": str(backup),
        "latest_live_run_id": latest_live_id,
        "restored_up_to_run_id": (latest_live_id - 1 if latest_live_id > 1 else None),
        "reason": reason,
        "rows_considered": int(len(rows)),
        "insert_rows": int(len(inserts)),
        "district_rows": int(len(district_group)),
        "state_rows": int(len(state_group)),
        "national_rows": int(len(national_group)),
        "total_restored_qty": float(round(sum(float(r[4]) for r in inserts), 6)),
    }

    REPORT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))

    conn.close()


if __name__ == "__main__":
    main()
