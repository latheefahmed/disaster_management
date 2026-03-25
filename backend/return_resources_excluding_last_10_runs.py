import json
import shutil
import sqlite3
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "backend.db"
REPORT_PATH = ROOT / "RETURN_RESOURCES_EXCEPT_LAST10_REPORT.json"

EXCLUDE_LAST_RUNS = max(0, int(os.getenv("EXCLUDE_LAST_RUNS", "10") or 10))
RUN_TAG = str(os.getenv("RETURN_RUN_TAG", "v1") or "v1").strip() or "v1"
REASON = f"global_return_excluding_last{EXCLUDE_LAST_RUNS}"
ACTOR_ID = f"global_return_except_last{EXCLUDE_LAST_RUNS}_{RUN_TAG}"


def backup_db() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / f"backend_pre_return_except_last10_{stamp}.db"
    shutil.copy2(DB_PATH, backup)
    return backup


def scope_key(
    allocation_source_scope: str | None,
    supply_level: str | None,
    district_code: str | None,
    state_code: str | None,
    origin_state_code: str | None,
):
    level = str(allocation_source_scope or supply_level or "district").strip().lower()
    if level == "district":
        return ("district", str(district_code or ""), str(state_code or ""))
    if level == "state":
        origin = str(origin_state_code or state_code or "")
        if origin.upper() == "NATIONAL":
            return ("national", None, None)
        return ("state", None, origin)
    if level == "national":
        return ("national", None, None)
    return ("district", str(district_code or ""), str(state_code or ""))


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB not found: {DB_PATH}")

    backup = backup_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    already_done = cur.execute(
        """
        SELECT COUNT(*)
        FROM stock_refill_transactions
        WHERE reason=? AND actor_id=?
        """,
        (REASON, ACTOR_ID),
    ).fetchone()[0]
    if int(already_done or 0) > 0:
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "skipped_already_applied",
            "db": str(DB_PATH),
            "backup": str(backup),
            "reason": REASON,
            "actor_id": ACTOR_ID,
        }
        REPORT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2))
        conn.close()
        return

    excluded_rows = cur.execute(
        """
        SELECT id
        FROM solver_runs
        ORDER BY id DESC
        LIMIT ?
        """
    , (int(EXCLUDE_LAST_RUNS),)).fetchall()
    excluded_run_ids = {int(r[0]) for r in excluded_rows}

    where_exclude = ""
    params: list = []
    if excluded_run_ids:
        placeholders = ",".join("?" for _ in excluded_run_ids)
        where_exclude = f" AND COALESCE(a.solver_run_id,0) NOT IN ({placeholders})"
        params.extend(sorted(excluded_run_ids))

    rows = cur.execute(
        f"""
        SELECT
            a.id,
            a.solver_run_id,
            a.district_code,
            a.state_code,
            a.resource_id,
            a.time,
            a.allocated_quantity,
            a.returned_quantity,
            a.allocation_source_scope,
            a.supply_level,
            a.origin_state_code
        FROM allocations a
        WHERE COALESCE(a.is_unmet,0)=0
          AND COALESCE(a.allocated_quantity,0) > 0
          {where_exclude}
        """,
        tuple(params),
    ).fetchall()

    updates = []
    return_rows = []
    refill_grouped = defaultdict(float)

    alloc_rows_scanned = 0
    alloc_rows_updated = 0
    total_new_return_qty = 0.0

    for r in rows:
        alloc_rows_scanned += 1

        alloc_id = int(r["id"])
        solver_run_id = int(r["solver_run_id"] or 0)
        district_code = str(r["district_code"] or "")
        state_code = str(r["state_code"] or "")
        resource_id = str(r["resource_id"] or "")
        time_slot = int(r["time"] or 0)

        allocated = float(r["allocated_quantity"] or 0.0)
        prev_returned = float(r["returned_quantity"] or 0.0)
        target_returned = allocated
        delta = max(0.0, target_returned - prev_returned)
        if delta <= 1e-9:
            continue

        updates.append((
            allocated,
            0.0,
            target_returned,
            "RETURNED",
            alloc_id,
        ))
        alloc_rows_updated += 1
        total_new_return_qty += delta

        return_rows.append((
            district_code,
            resource_id,
            time_slot,
            int(round(delta)),
            solver_run_id,
            REASON,
        ))

        scope, refill_district, refill_state = scope_key(
            r["allocation_source_scope"],
            r["supply_level"],
            district_code,
            state_code,
            r["origin_state_code"],
        )
        refill_grouped[(scope, refill_district, refill_state, resource_id, solver_run_id)] += delta

    if updates:
        cur.executemany(
            """
            UPDATE allocations
            SET claimed_quantity=?,
                consumed_quantity=?,
                returned_quantity=?,
                status=?
            WHERE id=?
            """,
            updates,
        )

    if return_rows:
        cur.executemany(
            """
            INSERT INTO returns (district_code, resource_id, time, quantity, solver_run_id, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            return_rows,
        )

    refill_rows = []
    for (scope, district_code, state_code, resource_id, solver_run_id), qty in refill_grouped.items():
        refill_rows.append((
            scope,
            district_code,
            state_code,
            resource_id,
            float(round(qty, 6)),
            REASON,
            "system",
            ACTOR_ID,
            "manual_refill",
            solver_run_id,
        ))

    if refill_rows:
        cur.executemany(
            """
            INSERT INTO stock_refill_transactions (
                scope, district_code, state_code, resource_id,
                quantity_delta, reason, actor_role, actor_id,
                source, solver_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            refill_rows,
        )

    conn.commit()

    payload = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "applied",
        "db": str(DB_PATH),
        "backup": str(backup),
        "excluded_last_10_run_ids": sorted(excluded_run_ids),
        "excluded_last_runs_count": int(EXCLUDE_LAST_RUNS),
        "alloc_rows_scanned": int(alloc_rows_scanned),
        "alloc_rows_updated": int(alloc_rows_updated),
        "returns_inserted": int(len(return_rows)),
        "refill_rows_inserted": int(len(refill_rows)),
        "total_new_return_quantity": float(round(total_new_return_qty, 6)),
    }
    REPORT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))

    conn.close()


if __name__ == "__main__":
    main()
