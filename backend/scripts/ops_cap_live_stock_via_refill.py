import json
from datetime import datetime, UTC

from app.database import SessionLocal
from app.models.district import District
from app.models.stock_refill_transaction import StockRefillTransaction
from app.services.kpi_service import get_district_stock_rows, get_state_stock_rows, get_national_stock_rows


TARGET_CAPS = {
    "R22": {"district": 2200.0, "state": 8000.0, "national": 60000.0},   # doctors
    "R13": {"district": 3500.0, "state": 15000.0, "national": 120000.0}, # family shelter kits
    "R12": {"district": 5000.0, "state": 20000.0, "national": 150000.0}, # plastic sheets
}


def _row_for(rows, rid: str):
    for r in rows:
        if str(r.get("resource_id")) == str(rid):
            return r
    return None


def main() -> None:
    db = SessionLocal()
    try:
        districts = db.query(District).all()
        states = sorted({str(d.state_code) for d in districts if d.state_code is not None})

        changes = []

        # District caps across all districts
        for d in districts:
            dcode = str(d.district_code)
            scode = str(d.state_code)
            rows = get_district_stock_rows(db, dcode)
            for rid, caps in TARGET_CAPS.items():
                row = _row_for(rows, rid)
                current = float((row or {}).get("district_stock") or 0.0)
                cap = float(caps["district"])
                if current > cap + 1e-6:
                    delta = cap - current  # negative adjustment
                    db.add(
                        StockRefillTransaction(
                            scope="district",
                            district_code=dcode,
                            state_code=scode,
                            resource_id=rid,
                            quantity_delta=float(delta),
                            reason="global_pool_realism_cap",
                            actor_role="system",
                            actor_id="ops_cap_live_stock_via_refill",
                            source="manual_refill",
                            solver_run_id=None,
                        )
                    )
                    changes.append({"scope": "district", "district_code": dcode, "state_code": scode, "resource_id": rid, "before": current, "cap": cap, "delta": float(delta)})

        # State caps (one per state)
        for scode in states:
            rows = get_state_stock_rows(db, scode)
            for rid, caps in TARGET_CAPS.items():
                row = _row_for(rows, rid)
                current = float((row or {}).get("state_stock") or 0.0)
                cap = float(caps["state"])
                if current > cap + 1e-6:
                    delta = cap - current
                    db.add(
                        StockRefillTransaction(
                            scope="state",
                            district_code=None,
                            state_code=scode,
                            resource_id=rid,
                            quantity_delta=float(delta),
                            reason="global_pool_realism_cap",
                            actor_role="system",
                            actor_id="ops_cap_live_stock_via_refill",
                            source="manual_refill",
                            solver_run_id=None,
                        )
                    )
                    changes.append({"scope": "state", "district_code": None, "state_code": scode, "resource_id": rid, "before": current, "cap": cap, "delta": float(delta)})

        # National caps
        nrows = get_national_stock_rows(db)
        for rid, caps in TARGET_CAPS.items():
            row = _row_for(nrows, rid)
            current = float((row or {}).get("national_stock") or 0.0)
            cap = float(caps["national"])
            if current > cap + 1e-6:
                delta = cap - current
                db.add(
                    StockRefillTransaction(
                        scope="national",
                        district_code=None,
                        state_code=None,
                        resource_id=rid,
                        quantity_delta=float(delta),
                        reason="global_pool_realism_cap",
                        actor_role="system",
                        actor_id="ops_cap_live_stock_via_refill",
                        source="manual_refill",
                        solver_run_id=None,
                    )
                )
                changes.append({"scope": "national", "district_code": None, "state_code": None, "resource_id": rid, "before": current, "cap": cap, "delta": float(delta)})

        db.commit()

        # Verify district 603 post-cap quick view
        post_603 = get_district_stock_rows(db, "603")
        verify_603 = {}
        for rid in TARGET_CAPS:
            row = _row_for(post_603, rid) or {}
            verify_603[rid] = {
                "district_stock": float(row.get("district_stock") or 0.0),
                "state_stock": float(row.get("state_stock") or 0.0),
                "national_stock": float(row.get("national_stock") or 0.0),
            }

        out = {
            "timestamp": datetime.now(UTC).isoformat(),
            "target_caps": TARGET_CAPS,
            "total_changes": len(changes),
            "changes_preview": changes[:120],
            "district_603_after": verify_603,
        }

        out_path = "OPS_LIVE_STOCK_CAP_REPORT.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)

        print(json.dumps({
            "out_path": out_path,
            "total_changes": len(changes),
            "district_603_after": verify_603,
        }, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
