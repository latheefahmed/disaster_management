import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "backend.db"

TABLES_TO_CLEAR = [
    "allocations",
    "final_demands",
    "inventory_snapshots",
    "shipment_plans",
    "scenario_explanations",
    "agent_recommendations",
    "agent_findings",
    "scenario_national_stock",
    "scenario_state_stock",
    "scenario_requests",
    "scenarios",
    "request_predictions",
    "returns",
    "consumptions",
    "claims",
    "resource_requests",
    "requests",
    "solver_runs",
]


def existing_tables(cur):
    rows = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def count_rows(cur, table):
    return int(cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("PRAGMA foreign_keys = OFF")

    exists = existing_tables(cur)
    targets = [t for t in TABLES_TO_CLEAR if t in exists]

    before = {t: count_rows(cur, t) for t in targets}

    # mark running live runs failed first (if solver_runs exists)
    if "solver_runs" in exists:
        cur.execute("UPDATE solver_runs SET status='failed' WHERE mode='live' AND status='running'")
        running_failed = cur.rowcount
    else:
        running_failed = 0

    for table in targets:
        cur.execute(f"DELETE FROM {table}")

    con.commit()

    after = {t: count_rows(cur, t) for t in targets}

    print("DB", str(DB_PATH))
    print("RUNNING_LIVE_MARKED_FAILED", int(running_failed))
    print("CLEARED_TABLES", len(targets))
    print("BEFORE", before)
    print("AFTER", after)

    con.close()


if __name__ == "__main__":
    main()
