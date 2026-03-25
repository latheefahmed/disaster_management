import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "backend.db"
REPORT = ROOT / "ZERO_ONE_PURGE_REPORT.json"

TARGETS = {
    "claims": ["quantity"],
    "returns": ["quantity"],
    "consumptions": ["quantity"],
    "allocations": ["allocated_quantity"],
    "requests": ["quantity", "allocated_quantity", "unmet_quantity", "final_demand_quantity"],
}


def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    return bool(cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def col_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    cols = cur.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(r[1]) == col for r in cols)


def backup_db() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DB.with_name(f"backend_pre_zero_one_purge_{stamp}.db")
    shutil.copy2(DB, out)
    return out


def main():
    if not DB.exists():
        raise FileNotFoundError(DB)

    backup = backup_db()

    con = sqlite3.connect(DB)
    cur = con.cursor()

    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "db": str(DB),
        "backup": str(backup),
        "tables": {},
    }

    try:
        cur.execute("PRAGMA foreign_keys = OFF")

        for table, cols in TARGETS.items():
            if not table_exists(cur, table):
                continue

            usable = [c for c in cols if col_exists(cur, table, c)]
            if not usable:
                continue

            before = int(cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

            where = " OR ".join([f"(COALESCE({c},0) >= 0 AND COALESCE({c},0) <= 1)" for c in usable])
            purge_count = int(cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])

            cur.execute(f"DELETE FROM {table} WHERE {where}")
            deleted = int(cur.rowcount or 0)

            after = int(cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

            report["tables"][table] = {
                "columns_checked": usable,
                "before": before,
                "matched_for_purge": purge_count,
                "deleted": deleted,
                "after": after,
            }

        con.commit()

    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    report["total_deleted"] = int(sum(v.get("deleted", 0) for v in report["tables"].values()))
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
