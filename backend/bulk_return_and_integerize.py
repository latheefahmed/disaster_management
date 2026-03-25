import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "backend.db"
REPORT_PATH = ROOT / "BULK_RETURN_INTEGERIZE_REPORT.json"


NUMERIC_TYPE_RE = re.compile(r"INT|REAL|FLOA|DOUB|NUM", re.IGNORECASE)
QTY_NAME_RE = re.compile(
    r"quantity|qty|allocated|claimed|consumed|returned|unmet|demand|delta|available|remaining",
    re.IGNORECASE,
)


def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def get_columns(cur: sqlite3.Cursor, table: str):
    return cur.execute(f"PRAGMA table_info({table})").fetchall()


def is_numeric_type(declared_type: str | None) -> bool:
    return bool(NUMERIC_TYPE_RE.search(str(declared_type or "")))


def round_int(value, *, min_value: int | None = None, max_value: int | None = None) -> int:
    if value is None:
        out = 0
    else:
        out = int(round(float(value)))
    if min_value is not None and out < min_value:
        out = min_value
    if max_value is not None and out > max_value:
        out = max_value
    return int(out)


def backup_db() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB_PATH.with_name(f"backend_pre_bulk_return_integerize_{stamp}.db")
    shutil.copy2(DB_PATH, backup)
    return backup


def get_latest_live_run_id(cur: sqlite3.Cursor) -> int | None:
    if not table_exists(cur, "solver_runs"):
        return None
    row = cur.execute(
        """
        SELECT id
        FROM solver_runs
        WHERE LOWER(COALESCE(status, ''))='completed'
          AND LOWER(COALESCE(mode, ''))='live'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    return int(row[0]) if row else None


def get_latest_scenario_id(cur: sqlite3.Cursor) -> int | None:
    if not table_exists(cur, "scenarios"):
        return None
    row = cur.execute("SELECT id FROM scenarios ORDER BY id DESC LIMIT 1").fetchone()
    return int(row[0]) if row else None


def keep_latest_20_allocation_ids(cur: sqlite3.Cursor) -> set[int]:
    if not table_exists(cur, "allocations"):
        return set()
    rows = cur.execute(
        """
        SELECT id
        FROM allocations
        WHERE COALESCE(is_unmet,0)=0
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()
    return {int(r[0]) for r in rows}


def bulk_return_older_allocations(cur: sqlite3.Cursor, keep_ids: set[int]):
    if not table_exists(cur, "allocations"):
        return {
            "rows_scanned": 0,
            "rows_updated": 0,
            "returns_inserted": 0,
            "kept_latest_20": 0,
        }

    where_not_keep = ""
    params: list = []
    if keep_ids:
        placeholders = ",".join("?" for _ in keep_ids)
        where_not_keep = f" AND id NOT IN ({placeholders})"
        params.extend(sorted(keep_ids))

    rows = cur.execute(
        f"""
        SELECT id, solver_run_id, district_code, resource_id, time,
               allocated_quantity, claimed_quantity, consumed_quantity, returned_quantity,
               overflow_reconciled_quantity
        FROM allocations
        WHERE COALESCE(is_unmet,0)=0
          {where_not_keep}
        """,
        tuple(params),
    ).fetchall()

    updates = []
    returns_to_insert = []

    for row in rows:
        (
            alloc_id,
            solver_run_id,
            district_code,
            resource_id,
            time_slot,
            allocated_qty,
            claimed_qty,
            consumed_qty,
            returned_qty,
            overflow_qty,
        ) = row

        allocated_i = round_int(allocated_qty, min_value=0)
        consumed_i = round_int(consumed_qty, min_value=0, max_value=allocated_i)
        claimed_i = allocated_i

        target_returned = max(0, allocated_i - consumed_i)
        prior_returned_i = round_int(returned_qty, min_value=0)
        new_returned = max(prior_returned_i, target_returned)
        if consumed_i + new_returned > allocated_i:
            new_returned = max(0, allocated_i - consumed_i)

        overflow_i = round_int(overflow_qty, min_value=0)

        if allocated_i <= 0:
            new_status = "allocated"
        elif consumed_i > 0 and (consumed_i + new_returned) >= allocated_i:
            new_status = "consumed"
        elif new_returned > 0 and (consumed_i + new_returned) >= allocated_i:
            new_status = "RETURNED"
        elif new_returned > 0:
            new_status = "partially_returned"
        else:
            new_status = "claimed"

        updates.append(
            (
                float(allocated_i),
                float(claimed_i),
                float(consumed_i),
                float(new_returned),
                float(overflow_i),
                new_status,
                int(alloc_id),
            )
        )

        delta_return = max(0, new_returned - prior_returned_i)
        if delta_return > 0:
            returns_to_insert.append(
                (
                    int(solver_run_id or 0),
                    str(district_code or ""),
                    str(resource_id or ""),
                    int(time_slot or 0),
                    int(delta_return),
                    "bulk_return_keep_latest_20",
                )
            )

    if updates:
        cur.executemany(
            """
            UPDATE allocations
            SET allocated_quantity=?,
                claimed_quantity=?,
                consumed_quantity=?,
                returned_quantity=?,
                overflow_reconciled_quantity=?,
                status=?
            WHERE id=?
            """,
            updates,
        )

    if returns_to_insert and table_exists(cur, "returns"):
        cur.executemany(
            """
            INSERT INTO returns (solver_run_id, district_code, resource_id, time, quantity, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            returns_to_insert,
        )

    return {
        "rows_scanned": int(len(rows)),
        "rows_updated": int(len(updates)),
        "returns_inserted": int(len(returns_to_insert)),
        "kept_latest_20": int(len(keep_ids)),
    }


def integerize_quantity_columns(cur: sqlite3.Cursor):
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    skip_tables = {
        "sqlite_sequence",
        "alembic_version",
    }

    table_stats: dict[str, dict] = {}
    total_cells = 0

    for table in tables:
        if table in skip_tables:
            continue
        cols = get_columns(cur, table)
        if not cols:
            continue

        candidate_cols = []
        for c in cols:
            col_name = str(c[1])
            col_type = str(c[2] or "")
            if is_numeric_type(col_type) and QTY_NAME_RE.search(col_name):
                candidate_cols.append(col_name)

        if not candidate_cols:
            continue

        rowid_rows = cur.execute(
            f"SELECT rowid, {', '.join(candidate_cols)} FROM {table}"
        ).fetchall()
        if not rowid_rows:
            continue

        updates = []
        changed_cells = 0

        for r in rowid_rows:
            rowid = int(r[0])
            vals = list(r[1:])
            new_vals = []
            row_changed = False
            for idx, val in enumerate(vals):
                col = candidate_cols[idx]
                if val is None:
                    new_vals.append(None)
                    continue
                rounded = float(round_int(val))
                if str(col).lower().endswith("quantity") and str(table) in {
                    "inventory_snapshots",
                    "scenario_state_stock",
                    "scenario_national_stock",
                }:
                    rounded = float(max(1, int(rounded)))
                if float(rounded) != float(val):
                    changed_cells += 1
                    row_changed = True
                new_vals.append(rounded)

            if row_changed:
                updates.append(tuple(new_vals + [rowid]))

        if updates:
            set_clause = ", ".join(f"{c}=?" for c in candidate_cols)
            cur.executemany(
                f"UPDATE {table} SET {set_clause} WHERE rowid=?",
                updates,
            )

        table_stats[table] = {
            "columns": candidate_cols,
            "rows": int(len(rowid_rows)),
            "row_updates": int(len(updates)),
            "cell_changes": int(changed_cells),
        }
        total_cells += int(changed_cells)

    return {
        "tables": table_stats,
        "total_cell_changes": int(total_cells),
    }


def enforce_nonzero_stock_floors(cur: sqlite3.Cursor, latest_live_run_id: int | None, latest_scenario_id: int | None):
    report = {
        "inventory_snapshots_updated": 0,
        "scenario_state_stock_updated": 0,
        "scenario_national_stock_updated": 0,
    }

    if latest_live_run_id is not None and table_exists(cur, "inventory_snapshots"):
        cur.execute(
            """
            UPDATE inventory_snapshots
            SET quantity = CASE
                WHEN quantity IS NULL THEN 1
                WHEN ROUND(quantity) < 1 THEN 1
                ELSE ROUND(quantity)
            END
            WHERE solver_run_id = ?
            """,
            (int(latest_live_run_id),),
        )
        report["inventory_snapshots_updated"] = int(cur.rowcount or 0)

    if latest_scenario_id is not None and table_exists(cur, "scenario_state_stock"):
        cur.execute(
            """
            UPDATE scenario_state_stock
            SET quantity = CASE
                WHEN quantity IS NULL THEN 1
                WHEN ROUND(quantity) < 1 THEN 1
                ELSE ROUND(quantity)
            END
            WHERE scenario_id = ?
            """,
            (int(latest_scenario_id),),
        )
        report["scenario_state_stock_updated"] = int(cur.rowcount or 0)

    if latest_scenario_id is not None and table_exists(cur, "scenario_national_stock"):
        cur.execute(
            """
            UPDATE scenario_national_stock
            SET quantity = CASE
                WHEN quantity IS NULL THEN 1
                WHEN ROUND(quantity) < 1 THEN 1
                ELSE ROUND(quantity)
            END
            WHERE scenario_id = ?
            """,
            (int(latest_scenario_id),),
        )
        report["scenario_national_stock_updated"] = int(cur.rowcount or 0)

    return report


def build_validation(cur: sqlite3.Cursor, latest_live_run_id: int | None, latest_scenario_id: int | None):
    checks = {}

    if table_exists(cur, "allocations"):
        checks["allocations_non_int_like_qty_rows"] = int(
            cur.execute(
                """
                SELECT COUNT(*) FROM allocations
                WHERE ABS(allocated_quantity - ROUND(allocated_quantity)) > 1e-9
                   OR ABS(claimed_quantity - ROUND(claimed_quantity)) > 1e-9
                   OR ABS(consumed_quantity - ROUND(consumed_quantity)) > 1e-9
                   OR ABS(returned_quantity - ROUND(returned_quantity)) > 1e-9
                   OR ABS(overflow_reconciled_quantity - ROUND(overflow_reconciled_quantity)) > 1e-9
                """
            ).fetchone()[0]
        )
        checks["allocations_older_than_latest20_not_returned"] = int(
            cur.execute(
                """
                WITH keep AS (
                    SELECT id FROM allocations
                    WHERE COALESCE(is_unmet,0)=0
                    ORDER BY id DESC
                    LIMIT 20
                )
                SELECT COUNT(*)
                FROM allocations a
                WHERE COALESCE(a.is_unmet,0)=0
                  AND a.id NOT IN (SELECT id FROM keep)
                  AND (COALESCE(a.allocated_quantity,0) - COALESCE(a.consumed_quantity,0) - COALESCE(a.returned_quantity,0)) > 1e-9
                """
            ).fetchone()[0]
        )

    if latest_live_run_id is not None and table_exists(cur, "inventory_snapshots"):
        checks["latest_inventory_nonzero_rows"] = int(
            cur.execute(
                "SELECT COUNT(*) FROM inventory_snapshots WHERE solver_run_id=? AND quantity >= 1",
                (int(latest_live_run_id),),
            ).fetchone()[0]
        )
        checks["latest_inventory_zero_or_negative_rows"] = int(
            cur.execute(
                "SELECT COUNT(*) FROM inventory_snapshots WHERE solver_run_id=? AND quantity < 1",
                (int(latest_live_run_id),),
            ).fetchone()[0]
        )

    if latest_scenario_id is not None and table_exists(cur, "scenario_state_stock"):
        checks["latest_state_stock_zero_or_negative_rows"] = int(
            cur.execute(
                "SELECT COUNT(*) FROM scenario_state_stock WHERE scenario_id=? AND quantity < 1",
                (int(latest_scenario_id),),
            ).fetchone()[0]
        )

    if latest_scenario_id is not None and table_exists(cur, "scenario_national_stock"):
        checks["latest_national_stock_zero_or_negative_rows"] = int(
            cur.execute(
                "SELECT COUNT(*) FROM scenario_national_stock WHERE scenario_id=? AND quantity < 1",
                (int(latest_scenario_id),),
            ).fetchone()[0]
        )

    return checks


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB not found: {DB_PATH}")

    backup = backup_db()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "db": str(DB_PATH),
        "backup": str(backup),
    }

    try:
        cur.execute("PRAGMA foreign_keys = OFF")

        latest_live_run_id = get_latest_live_run_id(cur)
        latest_scenario_id = get_latest_scenario_id(cur)
        keep_ids = keep_latest_20_allocation_ids(cur)

        report["latest_live_run_id"] = latest_live_run_id
        report["latest_scenario_id"] = latest_scenario_id

        report["allocation_return_pass"] = bulk_return_older_allocations(cur, keep_ids)
        report["integerize_pass"] = integerize_quantity_columns(cur)
        report["nonzero_stock_floor_pass"] = enforce_nonzero_stock_floors(
            cur,
            latest_live_run_id=latest_live_run_id,
            latest_scenario_id=latest_scenario_id,
        )

        con.commit()

        report["validation"] = build_validation(
            cur,
            latest_live_run_id=latest_live_run_id,
            latest_scenario_id=latest_scenario_id,
        )

    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
