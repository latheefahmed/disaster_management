import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "backend.db"
REPORT_PATH = Path(__file__).resolve().parent / "STRICT_CAP_SCALE_REPORT.json"

TABLE_CONFIG = {
    "allocations": ["allocated_quantity", "claimed_quantity", "consumed_quantity", "returned_quantity", "overflow_reconciled_quantity"],
    "claims": ["quantity"],
    "consumptions": ["quantity"],
    "returns": ["quantity"],
    "final_demands": ["demand_quantity"],
    "requests": ["quantity", "allocated_quantity", "unmet_quantity", "final_demand_quantity"],
    "inventory_snapshots": ["quantity"],
    "scenario_requests": ["quantity"],
    "scenario_state_stock": ["quantity"],
    "scenario_national_stock": ["quantity"],
    "shipment_plans": ["quantity"],
    "state_transfers": ["quantity"],
    "mutual_aid_requests": ["quantity_requested"],
    "pool_transactions": ["quantity_delta"],
    "stock_refill_transactions": ["quantity_delta"],
    "demand_learning_events": ["baseline_demand", "human_demand", "final_demand", "allocated", "unmet"],
    "priority_urgency_events": ["baseline_demand", "human_quantity", "final_demand", "allocated", "unmet"],
}


def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    return cur.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone() is not None


def cols(cur: sqlite3.Cursor, table: str) -> set[str]:
    return {r[1] for r in cur.execute(f"pragma table_info({table})").fetchall()}


def strict_cap_for_unit(unit: str) -> float:
    u = (unit or "").lower()
    if "liter" in u:
        return 50000.0
    if u == "kg":
        return 20000.0
    if "tablet" in u:
        return 1500000.0
    if u in ("units", "kits", "packets", "courses"):
        return 20000.0
    if "person_day" in u:
        return 30000.0
    return 25000.0


def build_resource_factors(cur: sqlite3.Cursor):
    meta = {}
    for rid, rname, unit in cur.execute("select resource_id, resource_name, unit from resources").fetchall():
        meta[str(rid)] = {"name": str(rname or rid), "unit": str(unit or "units")}

    factors = {}
    diagnostics = {}
    for rid, info in meta.items():
        mx = cur.execute(
            "select coalesce(max(abs(allocated_quantity)),0) from allocations where resource_id=?",
            (rid,),
        ).fetchone()[0] or 0.0
        mx = float(mx)
        cap = strict_cap_for_unit(info["unit"])
        factor = 1.0 if mx <= cap or mx <= 0 else float(cap / mx)
        factors[rid] = factor
        diagnostics[rid] = {
            "resource_name": info["name"],
            "unit": info["unit"],
            "max_before": mx,
            "strict_cap": cap,
            "factor": factor,
        }
    return factors, diagnostics


def scale_number(v: float | None, factor: float):
    if v is None:
        return None
    value = float(v)
    scaled = value * factor
    if abs(value) > 0 and abs(scaled) < 0.001:
        scaled = 0.001 if value > 0 else -0.001
    return round(scaled, 3)


def rebuild_summary_snapshots(cur: sqlite3.Cursor):
    runs = [int(r[0]) for r in cur.execute("select id from solver_runs where status='completed' and mode='live'").fetchall()]
    for run_id in runs:
        alloc = float(cur.execute("select coalesce(sum(allocated_quantity),0) from allocations where solver_run_id=? and is_unmet=0", (run_id,)).fetchone()[0] or 0.0)
        unmet = float(cur.execute("select coalesce(sum(allocated_quantity),0) from allocations where solver_run_id=? and is_unmet=1", (run_id,)).fetchone()[0] or 0.0)
        district_totals = {}
        for d, a, u in cur.execute(
            """
            select district_code,
                   coalesce(sum(case when is_unmet=0 then allocated_quantity else 0 end),0),
                   coalesce(sum(case when is_unmet=1 then allocated_quantity else 0 end),0)
            from allocations where solver_run_id=? group by district_code
            """,
            (run_id,),
        ).fetchall():
            district_totals[str(d)] = {"allocated_quantity": float(a or 0), "unmet_quantity": float(u or 0)}
        state_totals = {}
        for s, a, u in cur.execute(
            """
            select state_code,
                   coalesce(sum(case when is_unmet=0 then allocated_quantity else 0 end),0),
                   coalesce(sum(case when is_unmet=1 then allocated_quantity else 0 end),0)
            from allocations where solver_run_id=? group by state_code
            """,
            (run_id,),
        ).fetchall():
            state_totals[str(s)] = {"allocated_quantity": float(a or 0), "unmet_quantity": float(u or 0)}

        snap = {
            "totals": {
                "allocated_quantity": alloc,
                "unmet_quantity": unmet,
                "final_demand_quantity": alloc + unmet,
            },
            "district_totals": district_totals,
            "state_totals": state_totals,
        }
        cur.execute("update solver_runs set summary_snapshot_json=? where id=?", (json.dumps(snap), run_id))


def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB_PATH.with_name(f"backend_pre_strict_cap_scale_{stamp}.db")
    shutil.copy2(DB_PATH, backup)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    factors, diagnostics = build_resource_factors(cur)
    table_summary = {}

    try:
        cur.execute("begin")
        for table, qty_cols in TABLE_CONFIG.items():
            if not table_exists(cur, table):
                continue
            existing = cols(cur, table)
            cols_to_scale = [c for c in qty_cols if c in existing]
            if not cols_to_scale or "resource_id" not in existing:
                continue

            rows = cur.execute(f"select rowid, resource_id, {', '.join(cols_to_scale)} from {table}").fetchall()
            updates = []
            for row in rows:
                rowid = row[0]
                rid = str(row[1] or "")
                factor = float(factors.get(rid, 1.0))
                if factor >= 0.999999:
                    continue
                vals = [scale_number(v, factor) for v in row[2:]]
                updates.append(tuple(vals + [rowid]))

            if updates:
                set_clause = ", ".join(f"{c}=?" for c in cols_to_scale)
                cur.executemany(f"update {table} set {set_clause} where rowid=?", updates)
            table_summary[table] = {"updated_rows": len(updates)}

        rebuild_summary_snapshots(cur)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    report = {
        "status": "ok",
        "backup": str(backup),
        "resource_factors": diagnostics,
        "tables": table_summary,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "backup": str(backup),
        "report": str(REPORT_PATH),
        "tables_touched": len(table_summary),
    }, indent=2))


if __name__ == "__main__":
    main()
