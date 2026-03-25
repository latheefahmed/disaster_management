import glob
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "backend.db"
REPORT = ROOT / "BULK_RETURN_RESTOCK_RECONCILE_REPORT.json"


def _latest_bulk_backup() -> Path:
    matches = sorted(glob.glob(str(ROOT / "backend_pre_bulk_return_integerize_*.db")))
    if not matches:
        raise FileNotFoundError("No bulk-return backup db found")
    return Path(matches[-1])


def _scope_key(supply_level: str | None, district_code: str | None, state_code: str | None, origin_state_code: str | None):
    level = str(supply_level or "district").strip().lower()
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
    if not DB.exists():
        raise FileNotFoundError(f"Missing DB: {DB}")

    backup = _latest_bulk_backup()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if cur.execute(
        """
        SELECT COUNT(*)
        FROM stock_refill_transactions
        WHERE reason='bulk_return_restock' AND actor_id='bulk_return_reconcile'
        """
    ).fetchone()[0] > 0:
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "skipped_already_reconciled",
            "db": str(DB),
            "backup": str(backup),
        }
        REPORT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2))
        conn.close()
        return

    cur.execute("ATTACH DATABASE ? AS bkp", (str(backup),))

    rows = cur.execute(
        """
        SELECT
            a.id,
            a.resource_id,
            a.solver_run_id,
            a.supply_level,
            a.district_code,
            a.state_code,
            a.origin_state_code,
            COALESCE(a.returned_quantity, 0.0) AS current_returned,
            COALESCE(b.returned_quantity, 0.0) AS backup_returned
        FROM allocations a
        JOIN bkp.allocations b ON b.id = a.id
        WHERE COALESCE(a.is_unmet,0)=0
        """
    ).fetchall()

    grouped = defaultdict(float)
    changed_rows = 0

    for r in rows:
        delta = float(r["current_returned"] or 0.0) - float(r["backup_returned"] or 0.0)
        if delta <= 1e-9:
            continue
        changed_rows += 1
        scope, district_code, state_code = _scope_key(
            r["supply_level"],
            r["district_code"],
            r["state_code"],
            r["origin_state_code"],
        )
        key = (
            scope,
            district_code,
            state_code,
            str(r["resource_id"]),
            int(r["solver_run_id"] or 0),
        )
        grouped[key] += float(delta)

    inserts = []
    for (scope, district_code, state_code, resource_id, solver_run_id), qty in grouped.items():
        if qty <= 1e-9:
            continue
        inserts.append(
            (
                scope,
                district_code,
                state_code,
                resource_id,
                float(round(qty, 6)),
                "bulk_return_restock",
                "system",
                "bulk_return_reconcile",
                "manual_refill",
                int(solver_run_id),
            )
        )

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
    cur.execute("DETACH DATABASE bkp")

    preview = cur.execute(
        """
        SELECT scope, resource_id, SUM(quantity_delta) qty
        FROM stock_refill_transactions
        WHERE reason='bulk_return_restock' AND actor_id='bulk_return_reconcile'
        GROUP BY scope, resource_id
        ORDER BY qty DESC
        LIMIT 15
        """
    ).fetchall()

    payload = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "applied",
        "db": str(DB),
        "backup": str(backup),
        "alloc_rows_with_new_return_delta": int(changed_rows),
        "credit_rows_inserted": int(len(inserts)),
        "total_credit_quantity": float(round(sum(float(r[4]) for r in inserts), 6)),
        "top_credits": [
            {"scope": str(r[0]), "resource_id": str(r[1]), "quantity": float(r[2] or 0.0)}
            for r in preview
        ],
    }

    REPORT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))

    conn.close()


if __name__ == "__main__":
    main()
