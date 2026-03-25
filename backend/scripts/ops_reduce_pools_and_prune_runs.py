import json
from collections import defaultdict
from datetime import datetime

from sqlalchemy import text

from app.database import SessionLocal


# Doctors + tent-equivalent resources
TARGET_CAPS = {
    "R22": {"district_cap": 2200.0, "state_cap": 8000.0, "national_cap": 60000.0},   # doctors
    "R13": {"district_cap": 3500.0, "state_cap": 15000.0, "national_cap": 120000.0}, # family_shelter_kits (tent-equivalent)
    "R12": {"district_cap": 5000.0, "state_cap": 20000.0, "national_cap": 150000.0}, # plastic_sheets (shelter/tent support)
}

KEEP_LATEST_RUNS = 100


def fetch_resource_names(db):
    rows = db.execute(text("SELECT resource_id, resource_name FROM resources")).fetchall()
    return {str(r.resource_id): str(r.resource_name) for r in rows}


def latest_snapshot_time(db):
    row = db.execute(text("SELECT COALESCE(MAX(solver_run_id), 0) AS rid FROM inventory_snapshots")).first()
    run_id = int(row.rid or 0)
    t_row = db.execute(
        text(
            """
            SELECT COALESCE(MAX(time), 0) AS t
            FROM inventory_snapshots
            WHERE solver_run_id = :rid
            """
        ),
        {"rid": run_id},
    ).first()
    time_val = t_row._mapping.get("t") if t_row is not None else 0
    return run_id, int(time_val or 0)


def summarize_before_after(db, run_id, time_idx):
    out = {}
    for rid in TARGET_CAPS:
        district_vals = db.execute(
            text(
                """
                SELECT district_code, quantity
                FROM inventory_snapshots
                WHERE solver_run_id = :rid_run
                  AND time = :t
                  AND resource_id = :rid
                """
            ),
            {"rid_run": run_id, "t": time_idx, "rid": rid},
        ).fetchall()

        state_vals = db.execute(
            text(
                """
                SELECT state_code, quantity
                FROM scenario_state_stock
                WHERE scenario_id = (SELECT COALESCE(MAX(id), 0) FROM scenarios)
                  AND resource_id = :rid
                """
            ),
            {"rid": rid},
        ).fetchall()

        nat_vals = db.execute(
            text(
                """
                SELECT quantity
                FROM scenario_national_stock
                WHERE scenario_id = (SELECT COALESCE(MAX(id), 0) FROM scenarios)
                  AND resource_id = :rid
                """
            ),
            {"rid": rid},
        ).fetchall()

        out[rid] = {
            "district_count": len(district_vals),
            "district_max": max([float(r.quantity or 0.0) for r in district_vals], default=0.0),
            "district_avg": (
                sum(float(r.quantity or 0.0) for r in district_vals) / len(district_vals)
                if district_vals else 0.0
            ),
            "state_count": len(state_vals),
            "state_max": max([float(r.quantity or 0.0) for r in state_vals], default=0.0),
            "state_avg": (
                sum(float(r.quantity or 0.0) for r in state_vals) / len(state_vals)
                if state_vals else 0.0
            ),
            "national_count": len(nat_vals),
            "national_max": max([float(r.quantity or 0.0) for r in nat_vals], default=0.0),
            "national_avg": (
                sum(float(r.quantity or 0.0) for r in nat_vals) / len(nat_vals)
                if nat_vals else 0.0
            ),
        }
    return out


def apply_caps(db, run_id, time_idx):
    changes = defaultdict(int)

    for rid, caps in TARGET_CAPS.items():
        res = db.execute(
            text(
                """
                UPDATE inventory_snapshots
                SET quantity = CASE
                    WHEN quantity > :cap THEN :cap
                    WHEN quantity < 0 THEN 0
                    ELSE quantity
                END
                WHERE solver_run_id = :rid_run
                  AND time = :t
                  AND resource_id = :rid
                """
            ),
            {"cap": float(caps["district_cap"]), "rid_run": run_id, "t": time_idx, "rid": rid},
        )
        changes[f"district_{rid}"] += int(res.rowcount or 0)

        res = db.execute(
            text(
                """
                UPDATE scenario_state_stock
                SET quantity = CASE
                    WHEN quantity > :cap THEN :cap
                    WHEN quantity < 0 THEN 0
                    ELSE quantity
                END
                WHERE scenario_id = (SELECT COALESCE(MAX(id), 0) FROM scenarios)
                  AND resource_id = :rid
                """
            ),
            {"cap": float(caps["state_cap"]), "rid": rid},
        )
        changes[f"state_{rid}"] += int(res.rowcount or 0)

        res = db.execute(
            text(
                """
                UPDATE scenario_national_stock
                SET quantity = CASE
                    WHEN quantity > :cap THEN :cap
                    WHEN quantity < 0 THEN 0
                    ELSE quantity
                END
                WHERE scenario_id = (SELECT COALESCE(MAX(id), 0) FROM scenarios)
                  AND resource_id = :rid
                """
            ),
            {"cap": float(caps["national_cap"]), "rid": rid},
        )
        changes[f"national_{rid}"] += int(res.rowcount or 0)

    return dict(changes)


def find_run_link_columns(db):
    tables = [r[0] for r in db.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")).fetchall()]
    refs = {}
    for t in tables:
        cols = db.execute(text(f"PRAGMA table_info({t})")).fetchall()
        names = [str(c[1]) for c in cols]
        hit = [n for n in names if n in {"solver_run_id", "run_id"}]
        if hit:
            refs[t] = hit
    return refs


def prune_runs(db):
    keep_ids = [int(r.id) for r in db.execute(text("SELECT id FROM solver_runs ORDER BY id DESC LIMIT :n"), {"n": KEEP_LATEST_RUNS}).fetchall()]
    if not keep_ids:
        return {"kept": 0, "deleted_runs": 0, "deleted_rows": {}}

    refs = find_run_link_columns(db)
    deleted_rows = {}

    # First remove rows linked by solver_run_id/run_id from dependent tables.
    for table, cols in refs.items():
        if table == "solver_runs":
            continue
        col = "solver_run_id" if "solver_run_id" in cols else "run_id"
        res = db.execute(
            text(
                f"DELETE FROM {table} WHERE {col} NOT IN ({','.join(str(i) for i in keep_ids)})"
            )
        )
        deleted_rows[table] = int(res.rowcount or 0)

    # Also prune requests by run_id when present.
    try:
        res = db.execute(
            text(
                f"DELETE FROM requests WHERE run_id IS NOT NULL AND run_id NOT IN ({','.join(str(i) for i in keep_ids)})"
            )
        )
        deleted_rows["requests_by_run"] = int(res.rowcount or 0)
    except Exception:
        pass

    # Finally prune solver_runs itself.
    res = db.execute(
        text(
            f"DELETE FROM solver_runs WHERE id NOT IN ({','.join(str(i) for i in keep_ids)})"
        )
    )
    deleted_runs = int(res.rowcount or 0)

    # Explicitly satisfy user request: remove runs below 800 if still present.
    res = db.execute(text("DELETE FROM solver_runs WHERE id < 800"))
    deleted_runs += int(res.rowcount or 0)

    return {
        "kept": len(keep_ids),
        "min_kept": min(keep_ids),
        "max_kept": max(keep_ids),
        "deleted_runs": deleted_runs,
        "deleted_rows": deleted_rows,
    }


def main():
    db = SessionLocal()
    try:
        resource_names = fetch_resource_names(db)
        run_id, time_idx = latest_snapshot_time(db)
        before = summarize_before_after(db, run_id, time_idx)

        cap_changes = apply_caps(db, run_id, time_idx)
        prune_report = prune_runs(db)

        db.commit()

        after = summarize_before_after(db, run_id, time_idx)

        report = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "latest_inventory_run_id": run_id,
            "latest_inventory_time": time_idx,
            "targets": {
                rid: {
                    "name": resource_names.get(rid, rid),
                    **caps,
                }
                for rid, caps in TARGET_CAPS.items()
            },
            "before": before,
            "after": after,
            "cap_changes": cap_changes,
            "prune_report": prune_report,
        }

        out_path = "OPS_POOL_REDUCTION_AND_RUN_PRUNE_REPORT.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(json.dumps({
            "out_path": out_path,
            "latest_inventory_run_id": run_id,
            "cap_changes": cap_changes,
            "prune_report": prune_report,
        }, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
