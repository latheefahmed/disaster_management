import json
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DB = Path(__file__).resolve().parent / "backend.db"
REPORT = Path(__file__).resolve().parent / "PERSISTED_STOCK_REBALANCE_REPORT.json"


def base_by_unit(unit: str) -> float:
    u = str(unit or "").lower()
    if "liter" in u:
        return 120.0
    if u == "kg":
        return 80.0
    if "tablet" in u:
        return 1500.0
    if "person_day" in u:
        return 120.0
    if u in {"units", "kits", "packets", "courses", "cylinders", "packs"}:
        return 8.0
    return 10.0


def run():
    if not DB.exists():
        raise SystemExit("backend.db not found")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB.with_name(f"backend_pre_persisted_rebalance_{stamp}.db")
    shutil.copy2(DB, backup)

    con = sqlite3.connect(DB)
    cur = con.cursor()

    latest_run = cur.execute("select id from solver_runs where status='completed' and mode='live' order by id desc limit 1").fetchone()
    latest_run = int(latest_run[0]) if latest_run else None
    latest_scenario = cur.execute("select id from scenarios order by id desc limit 1").fetchone()
    latest_scenario = int(latest_scenario[0]) if latest_scenario else None

    resources = cur.execute("select resource_id, resource_name, unit from resources").fetchall()
    districts = cur.execute("select district_code, state_code from districts").fetchall()

    # demand proxy multipliers from latest 100 runs
    run_ids = [int(r[0]) for r in cur.execute("select id from solver_runs where status='completed' and mode='live' order by id desc limit 100").fetchall()]
    district_demand = defaultdict(float)
    if run_ids:
        in_clause = ",".join(str(r) for r in run_ids)
        for d, q in cur.execute(
            f"select district_code, coalesce(sum(demand_quantity),0) from final_demands where solver_run_id in ({in_clause}) group by district_code"
        ).fetchall():
            district_demand[str(d)] += float(q or 0)
    if not district_demand:
        for d, _ in districts:
            district_demand[str(d)] = 1.0

    vals = sorted([v for v in district_demand.values() if v > 0])
    med = vals[len(vals)//2] if vals else 1.0
    district_mult = {d: max(0.7, min(1.5, (v / med) ** 0.18 if med > 0 else 1.0)) for d, v in district_demand.items()}

    state_demand = defaultdict(float)
    for d, s in districts:
        state_demand[str(s)] += float(district_demand.get(str(d), 1.0))
    svals = sorted([v for v in state_demand.values() if v > 0])
    smed = svals[len(svals)//2] if svals else 1.0
    state_mult = {s: max(0.8, min(1.4, (v / smed) ** 0.12 if smed > 0 else 1.0)) for s, v in state_demand.items()}

    district_updates = 0
    state_updates = 0
    national_updates = 0

    try:
        cur.execute("begin")

        # 1) District persisted stock floor in inventory_snapshots for latest run
        if latest_run is not None:
            existing_d = {
                (str(d), str(r)): float(q or 0.0)
                for d, r, q in cur.execute(
                    "select district_code, resource_id, coalesce(sum(quantity),0) from inventory_snapshots where solver_run_id=? group by district_code, resource_id",
                    (latest_run,),
                ).fetchall()
            }

            for dcode, scode in districts:
                dcode = str(dcode)
                for rid, rname, unit in resources:
                    rid = str(rid)
                    current = float(existing_d.get((dcode, rid), 0.0))
                    target = base_by_unit(unit) * float(district_mult.get(dcode, 1.0))
                    # enforce a realistic floor only when near-zero/missing
                    if current < (0.25 * target):
                        delta = max(0.0, target - current)
                        if delta > 0.0001:
                            cur.execute(
                                "insert into inventory_snapshots (solver_run_id, district_code, resource_id, time, quantity, created_at) values (?, ?, ?, 0, ?, datetime('now'))",
                                (latest_run, dcode, rid, float(round(delta, 3))),
                            )
                            district_updates += 1

        # 2) State scenario stock floor
        if latest_scenario is not None:
            existing_s = {
                (str(s), str(r)): float(q or 0.0)
                for s, r, q in cur.execute(
                    "select state_code, resource_id, coalesce(sum(quantity),0) from scenario_state_stock where scenario_id=? group by state_code, resource_id",
                    (latest_scenario,),
                ).fetchall()
            }

            all_states = sorted({str(s) for _, s in districts})
            for scode in all_states:
                sm = float(state_mult.get(scode, 1.0))
                for rid, rname, unit in resources:
                    rid = str(rid)
                    current = float(existing_s.get((scode, rid), 0.0))
                    target = base_by_unit(unit) * 20.0 * sm
                    if current < (0.3 * target):
                        delta = max(0.0, target - current)
                        if delta > 0.0001:
                            cur.execute(
                                "insert into scenario_state_stock (scenario_id, state_code, resource_id, quantity) values (?, ?, ?, ?)",
                                (latest_scenario, scode, rid, float(round(delta, 3))),
                            )
                            state_updates += 1

            # 3) National scenario stock floor
            existing_n = {
                str(r): float(q or 0.0)
                for r, q in cur.execute(
                    "select resource_id, coalesce(sum(quantity),0) from scenario_national_stock where scenario_id=? group by resource_id",
                    (latest_scenario,),
                ).fetchall()
            }
            for rid, rname, unit in resources:
                rid = str(rid)
                current = float(existing_n.get(rid, 0.0))
                target = base_by_unit(unit) * 200.0
                if current < (0.3 * target):
                    delta = max(0.0, target - current)
                    if delta > 0.0001:
                        cur.execute(
                            "insert into scenario_national_stock (scenario_id, resource_id, quantity) values (?, ?, ?)",
                            (latest_scenario, rid, float(round(delta, 3))),
                        )
                        national_updates += 1

        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    report = {
        "status": "ok",
        "backup": str(backup),
        "latest_run": latest_run,
        "latest_scenario": latest_scenario,
        "district_rows_inserted": district_updates,
        "state_rows_inserted": state_updates,
        "national_rows_inserted": national_updates,
        "note": "Persisted stock floors to avoid artificial zero stocks and reduce runtime fallback dependence",
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
