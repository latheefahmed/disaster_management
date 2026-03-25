import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "core_engine" / "phase4" / "resources" / "synthetic_data"

DISTRICT_FILE = DATA_DIR / "district_resource_stock.csv"
STATE_FILE = DATA_DIR / "state_resource_stock.csv"
NATIONAL_FILE = DATA_DIR / "national_resource_stock.csv"

# Map user "tents" to shelter resources used in dataset.
CAPS = {
    "district": {
        "R22": 2000.0,   # doctors
        "R13": 3500.0,   # family_shelter_kits (tent-equivalent)
        "R12": 5000.0,   # plastic_sheets (shelter/tent support)
    },
    "state": {
        "R22": 8000.0,
        "R13": 15000.0,
        "R12": 20000.0,
    },
    "national": {
        "R22": 60000.0,
        "R13": 120000.0,
        "R12": 150000.0,
    },
}


def _rewrite(path: Path, scope: str):
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    changed = 0
    for row in rows:
        rid = str(row.get("resource_id") or "").strip()
        if rid not in CAPS[scope]:
            continue
        try:
            qty = float(row.get("quantity") or 0.0)
        except Exception:
            qty = 0.0
        cap = float(CAPS[scope][rid])
        new_qty = min(max(0.0, qty), cap)
        if abs(new_qty - qty) > 1e-9:
            row["quantity"] = str(int(new_qty)) if abs(new_qty - round(new_qty)) < 1e-9 else f"{new_qty:.6f}".rstrip("0").rstrip(".")
            changed += 1

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    return {"file": str(path), "rows": len(rows), "changed": changed}


def main():
    report = {
        "district": _rewrite(DISTRICT_FILE, "district"),
        "state": _rewrite(STATE_FILE, "state"),
        "national": _rewrite(NATIONAL_FILE, "national"),
        "caps": CAPS,
    }
    out_path = ROOT / "backend" / "OPS_DOWNSCALE_STOCK_CSV_REPORT.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"out_path": str(out_path), **report}, indent=2))


if __name__ == "__main__":
    main()
