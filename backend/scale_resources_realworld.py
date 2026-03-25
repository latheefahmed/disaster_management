import json
import math
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "backend.db"
REPORT_PATH = Path(__file__).resolve().parent / "REALWORLD_SCALE_REPORT.json"

TABLE_CONFIG = {
    "allocations": {
        "qty_cols": ["allocated_quantity", "claimed_quantity", "consumed_quantity", "returned_quantity", "overflow_reconciled_quantity"],
        "positive_only": True,
    },
    "claims": {"qty_cols": ["quantity"], "positive_only": True},
    "consumptions": {"qty_cols": ["quantity"], "positive_only": True},
    "returns": {"qty_cols": ["quantity"], "positive_only": True},
    "final_demands": {"qty_cols": ["demand_quantity"], "positive_only": True},
    "requests": {"qty_cols": ["quantity", "allocated_quantity", "unmet_quantity", "final_demand_quantity"], "positive_only": True},
    "inventory_snapshots": {"qty_cols": ["quantity"], "positive_only": True},
    "scenario_requests": {"qty_cols": ["quantity"], "positive_only": True},
    "scenario_state_stock": {"qty_cols": ["quantity"], "positive_only": True},
    "scenario_national_stock": {"qty_cols": ["quantity"], "positive_only": True},
    "shipment_plans": {"qty_cols": ["quantity"], "positive_only": True},
    "state_transfers": {"qty_cols": ["quantity"], "positive_only": True},
    "mutual_aid_requests": {"qty_cols": ["quantity_requested"], "positive_only": True},
    "pool_transactions": {"qty_cols": ["quantity_delta"], "positive_only": False},
    "stock_refill_transactions": {"qty_cols": ["quantity_delta"], "positive_only": False},
    "demand_learning_events": {"qty_cols": ["baseline_demand", "human_demand", "final_demand", "allocated", "unmet"], "positive_only": True},
    "priority_urgency_events": {"qty_cols": ["baseline_demand", "human_quantity", "final_demand", "allocated", "unmet"], "positive_only": True},
}

RESOURCE_TARGET_OVERRIDES = {
    "diesel_liters": 12000.0,
    "bulk_water_liters": 25000.0,
    "bottled_water_liters": 12000.0,
    "water_purification_tablets": 500000.0,
    "food_packets": 15000.0,
    "rice_kg": 10000.0,
    "wheat_kg": 10000.0,
    "tents": 5000.0,
    "tarpaulins": 6000.0,
    "blankets": 15000.0,
    "sleeping_mats": 15000.0,
}


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    arr = sorted(values)
    pos = (len(arr) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(arr[lo])
    w = pos - lo
    return float(arr[lo] * (1.0 - w) + arr[hi] * w)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def is_integer_like_unit(unit: str) -> bool:
    u = (unit or "").lower()
    if "liter" in u or u == "kg":
        return False
    return True


def default_target_by_unit(unit: str) -> float:
    u = (unit or "").lower()
    if "liter" in u:
        return 8000.0
    if u == "kg":
        return 6000.0
    if "tablet" in u:
        return 200000.0
    if "person_day" in u:
        return 12000.0
    if "packet" in u:
        return 6000.0
    if "kit" in u:
        return 3000.0
    if "course" in u:
        return 4000.0
    return 5000.0


def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    row = cur.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone()
    return row is not None


def existing_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    return {r[1] for r in cur.execute(f"pragma table_info({table})").fetchall()}


def build_population_proxies(cur: sqlite3.Cursor):
    run_rows = cur.execute(
        "select id from solver_runs where status='completed' and mode='live' order by id desc limit 100"
    ).fetchall()
    run_ids = [int(r[0]) for r in run_rows]
    district_totals = defaultdict(float)

    if run_ids and table_exists(cur, "final_demands"):
        in_clause = ",".join(str(r) for r in run_ids)
        for district_code, qty in cur.execute(
            f"select district_code, coalesce(sum(demand_quantity),0) from final_demands where solver_run_id in ({in_clause}) group by district_code"
        ).fetchall():
            district_totals[str(district_code)] += float(qty or 0.0)

    if not district_totals and table_exists(cur, "requests"):
        for district_code, qty in cur.execute(
            "select district_code, coalesce(sum(quantity),0) from requests group by district_code"
        ).fetchall():
            district_totals[str(district_code)] += float(qty or 0.0)

    if not district_totals and table_exists(cur, "districts"):
        for district_code, in cur.execute("select district_code from districts").fetchall():
            district_totals[str(district_code)] = 1.0

    district_values = [v for v in district_totals.values() if v > 0]
    district_median = quantile(district_values, 0.5) if district_values else 1.0
    district_mult = {
        d: clamp((v / district_median) ** 0.2 if district_median > 0 else 1.0, 0.75, 1.25)
        for d, v in district_totals.items()
    }

    state_map = {}
    if table_exists(cur, "districts"):
        for d, s in cur.execute("select district_code, state_code from districts").fetchall():
            state_map[str(d)] = str(s)

    state_totals = defaultdict(float)
    for d, v in district_totals.items():
        s = state_map.get(str(d))
        if s:
            state_totals[s] += float(v)

    state_values = [v for v in state_totals.values() if v > 0]
    state_median = quantile(state_values, 0.5) if state_values else 1.0
    state_mult = {
        s: clamp((v / state_median) ** 0.12 if state_median > 0 else 1.0, 0.85, 1.15)
        for s, v in state_totals.items()
    }

    return district_mult, state_mult


def build_resource_scale_factors(cur: sqlite3.Cursor):
    resources = {}
    if table_exists(cur, "resources"):
        for rid, name, unit in cur.execute("select resource_id, resource_name, unit from resources").fetchall():
            resources[str(rid)] = {
                "name": str(name or rid),
                "unit": str(unit or "units"),
            }

    samples = defaultdict(list)

    if table_exists(cur, "final_demands"):
        for rid, qty in cur.execute("select resource_id, demand_quantity from final_demands where demand_quantity > 0").fetchall():
            samples[str(rid)].append(float(qty))

    if table_exists(cur, "requests"):
        for rid, qty in cur.execute("select resource_id, quantity from requests where quantity > 0").fetchall():
            samples[str(rid)].append(float(qty))

    if table_exists(cur, "allocations"):
        for rid, qty in cur.execute("select resource_id, allocated_quantity from allocations where allocated_quantity > 0").fetchall():
            samples[str(rid)].append(float(qty))

    factors = {}
    diagnostics = {}

    for rid, meta in resources.items():
        vals = samples.get(rid, [])
        p95 = quantile(vals, 0.95) if vals else 0.0
        p99 = quantile(vals, 0.99) if vals else 0.0
        vmax = max(vals) if vals else 0.0
        name = meta["name"]
        unit = meta["unit"]
        target = RESOURCE_TARGET_OVERRIDES.get(name, default_target_by_unit(unit))
        factor_p95 = 1.0
        if p95 > 0 and p95 > target:
            factor_p95 = target / p95

        hard_cap = target * 3.0
        factor_cap = 1.0
        if vmax > hard_cap and vmax > 0:
            factor_cap = hard_cap / vmax

        factor = min(factor_p95, factor_cap)
        factor = clamp(factor, 0.00001, 1.0)
        factors[rid] = factor
        diagnostics[rid] = {
            "resource_name": name,
            "unit": unit,
            "p95_before": p95,
            "p99_before": p99,
            "max_before": vmax,
            "target_p95": target,
            "hard_cap": hard_cap,
            "scale_factor": factor,
        }

    return resources, factors, diagnostics


def scale_value(value: float | None, factor: float, integer_like: bool, positive_only: bool) -> float | int | None:
    if value is None:
        return None
    v = float(value)
    scaled = v * factor

    if integer_like:
        r = int(round(scaled))
        if positive_only:
            if v > 0 and r <= 0:
                r = 1
            if r < 0:
                r = 0
            return r
        if v > 0 and r <= 0:
            r = 1
        if v < 0 and r >= 0:
            r = -1
        return r

    r = round(scaled, 3)
    if positive_only:
        if v > 0 and r <= 0:
            r = 0.001
        if r < 0:
            r = 0.0
    return r


def rebuild_summary_snapshots(cur: sqlite3.Cursor):
    runs = [int(r[0]) for r in cur.execute("select id from solver_runs where status='completed' and mode='live'").fetchall()]
    for run_id in runs:
        allocated_total = float(cur.execute(
            "select coalesce(sum(allocated_quantity),0) from allocations where solver_run_id=? and is_unmet=0",
            (run_id,),
        ).fetchone()[0] or 0.0)
        unmet_total = float(cur.execute(
            "select coalesce(sum(allocated_quantity),0) from allocations where solver_run_id=? and is_unmet=1",
            (run_id,),
        ).fetchone()[0] or 0.0)

        district_totals = {}
        for district_code, allocated, unmet in cur.execute(
            """
            select district_code,
                   coalesce(sum(case when is_unmet=0 then allocated_quantity else 0 end),0) as allocated,
                   coalesce(sum(case when is_unmet=1 then allocated_quantity else 0 end),0) as unmet
            from allocations
            where solver_run_id=?
            group by district_code
            """,
            (run_id,),
        ).fetchall():
            district_totals[str(district_code)] = {
                "allocated_quantity": float(allocated or 0.0),
                "unmet_quantity": float(unmet or 0.0),
            }

        state_totals = {}
        for state_code, allocated, unmet in cur.execute(
            """
            select state_code,
                   coalesce(sum(case when is_unmet=0 then allocated_quantity else 0 end),0) as allocated,
                   coalesce(sum(case when is_unmet=1 then allocated_quantity else 0 end),0) as unmet
            from allocations
            where solver_run_id=?
            group by state_code
            """,
            (run_id,),
        ).fetchall():
            state_totals[str(state_code)] = {
                "allocated_quantity": float(allocated or 0.0),
                "unmet_quantity": float(unmet or 0.0),
            }

        snapshot = {
            "totals": {
                "allocated_quantity": allocated_total,
                "unmet_quantity": unmet_total,
                "final_demand_quantity": float(allocated_total + unmet_total),
            },
            "district_totals": district_totals,
            "state_totals": state_totals,
        }

        cur.execute(
            "update solver_runs set summary_snapshot_json=? where id=?",
            (json.dumps(snapshot), run_id),
        )


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DB_PATH.with_name(f"backend_pre_realworld_scale_{stamp}.db")
    shutil.copy2(DB_PATH, backup_path)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    district_mult, state_mult = build_population_proxies(cur)
    resources, resource_factors, factor_diag = build_resource_scale_factors(cur)

    table_summary = {}

    try:
        cur.execute("begin")

        for table, cfg in TABLE_CONFIG.items():
            if not table_exists(cur, table):
                continue

            cols_existing = existing_columns(cur, table)
            qty_cols = [c for c in cfg["qty_cols"] if c in cols_existing]
            if not qty_cols or "resource_id" not in cols_existing:
                continue

            has_district = "district_code" in cols_existing
            has_state = "state_code" in cols_existing

            select_cols = ["rowid", "resource_id"]
            if has_district:
                select_cols.append("district_code")
            if has_state:
                select_cols.append("state_code")
            select_cols.extend(qty_cols)

            rows = cur.execute(f"select {', '.join(select_cols)} from {table}").fetchall()
            if not rows:
                continue

            updates = []
            before_after = {col: {"before": 0.0, "after": 0.0} for col in qty_cols}

            for row in rows:
                idx = 0
                rowid = row[idx]
                idx += 1
                rid = str(row[idx] or "")
                idx += 1

                district_code = None
                state_code = None
                if has_district:
                    district_code = str(row[idx]) if row[idx] is not None else None
                    idx += 1
                if has_state:
                    state_code = str(row[idx]) if row[idx] is not None else None
                    idx += 1

                base_factor = float(resource_factors.get(rid, 1.0))
                d_mult = float(district_mult.get(str(district_code), 1.0)) if district_code else 1.0
                s_mult = float(state_mult.get(str(state_code), 1.0)) if state_code else 1.0
                combined_factor = clamp(base_factor * d_mult * s_mult, 0.00001, 1.0)

                meta = resources.get(rid, {"unit": "units"})
                integer_like = is_integer_like_unit(str(meta.get("unit") or "units"))

                scaled_values = []
                changed = False

                for col in qty_cols:
                    val = row[idx]
                    idx += 1
                    if val is None:
                        scaled_values.append(None)
                        continue

                    before_after[col]["before"] += float(val)
                    positive_only = bool(cfg.get("positive_only", True))
                    scaled = scale_value(val, combined_factor, integer_like, positive_only)
                    before_after[col]["after"] += float(scaled or 0.0)
                    scaled_values.append(scaled)
                    if float(scaled or 0.0) != float(val or 0.0):
                        changed = True

                if changed:
                    updates.append(tuple(scaled_values + [rowid]))

            if updates:
                set_clause = ", ".join(f"{c}=?" for c in qty_cols)
                cur.executemany(
                    f"update {table} set {set_clause} where rowid=?",
                    updates,
                )

            table_summary[table] = {
                "updated_rows": len(updates),
                "columns": before_after,
            }

        rebuild_summary_snapshots(cur)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    report = {
        "timestamp": datetime.now().isoformat(),
        "database": str(DB_PATH),
        "backup": str(backup_path),
        "method": {
            "resource_scaling": "Per-resource p95-to-target scaling by unit + resource overrides",
            "population_weighting": "District/state proxy weighting from latest 100-run demand signal",
            "snapshot_rebuild": True,
        },
        "resource_factors": factor_diag,
        "table_summary": table_summary,
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "backup": str(backup_path),
        "report": str(REPORT_PATH),
        "tables_touched": len(table_summary),
    }, indent=2))


if __name__ == "__main__":
    main()
