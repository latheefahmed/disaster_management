from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOLVER_SCRIPT = ROOT / "core_engine" / "phase4" / "optimization" / "just_runs_cbc.py"
OUTPUT_DIR = ROOT / "core_engine" / "phase4" / "optimization" / "output"
SCENARIO_DIR = ROOT / "core_engine" / "phase4" / "scenarios" / "generated" / "validation_matrix"
SCENARIO_DIR.mkdir(parents=True, exist_ok=True)


SCENARIOS = [
    {
        "name": "district_only_sufficient",
        "demand": [{"district_code": "1", "resource_id": "R1", "time": 1, "demand": 10}],
        "district_stock": [{"district_code": "1", "resource_id": "R1", "quantity": 100}],
        "state_stock": [{"state_code": "1", "resource_id": "R1", "quantity": 0}],
        "national_stock": [{"resource_id": "R1", "quantity": 0}],
        "expected": {
            "allocated_total": 10.0,
            "unmet_total": 0.0,
            "district_alloc_min": 10.0,
            "state_in_min": 0.0,
            "national_in_min": 0.0,
        },
    },
    {
        "name": "district_then_state",
        "demand": [{"district_code": "1", "resource_id": "R1", "time": 1, "demand": 10}],
        "district_stock": [{"district_code": "1", "resource_id": "R1", "quantity": 5}],
        "state_stock": [{"state_code": "1", "resource_id": "R1", "quantity": 100}],
        "national_stock": [{"resource_id": "R1", "quantity": 0}],
        "expected": {
            "allocated_total": 10.0,
            "unmet_total": 0.0,
            "district_alloc_min": 5.0,
            "state_in_min": 5.0,
            "national_in_min": 0.0,
        },
    },
    {
        "name": "district_then_national",
        "demand": [{"district_code": "1", "resource_id": "R1", "time": 1, "demand": 10}],
        "district_stock": [{"district_code": "1", "resource_id": "R1", "quantity": 5}],
        "state_stock": [{"state_code": "1", "resource_id": "R1", "quantity": 0}],
        "national_stock": [{"resource_id": "R1", "quantity": 100}],
        "expected": {
            "allocated_total": 10.0,
            "unmet_total": 0.0,
            "district_alloc_min": 5.0,
            "state_in_min": 0.0,
            "national_in_min": 5.0,
        },
    },
    {
        "name": "full_shortage",
        "demand": [{"district_code": "1", "resource_id": "R1", "time": 1, "demand": 10}],
        "district_stock": [{"district_code": "1", "resource_id": "R1", "quantity": 0}],
        "state_stock": [{"state_code": "1", "resource_id": "R1", "quantity": 0}],
        "national_stock": [{"resource_id": "R1", "quantity": 0}],
        "expected": {
            "allocated_total": 0.0,
            "unmet_total": 10.0,
            "district_alloc_min": 0.0,
            "state_in_min": 0.0,
            "national_in_min": 0.0,
        },
    },
]


def _write_csv(rows: list[dict], path: Path, columns: list[str]) -> Path:
    df = pd.DataFrame(rows, columns=columns)
    df.to_csv(path, index=False)
    return path


def _sum_col(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0.0).sum())


def run_one(s: dict) -> dict:
    demand_path = _write_csv(s["demand"], SCENARIO_DIR / f"{s['name']}_demand.csv", ["district_code", "resource_id", "time", "demand"])
    dstock_path = _write_csv(s["district_stock"], SCENARIO_DIR / f"{s['name']}_district_stock.csv", ["district_code", "resource_id", "quantity"])
    sstock_path = _write_csv(s["state_stock"], SCENARIO_DIR / f"{s['name']}_state_stock.csv", ["state_code", "resource_id", "quantity"])
    nstock_path = _write_csv(s["national_stock"], SCENARIO_DIR / f"{s['name']}_national_stock.csv", ["resource_id", "quantity"])

    cmd = [
        sys.executable,
        str(SOLVER_SCRIPT),
        "--demand",
        str(demand_path),
        "--district-stock",
        str(dstock_path),
        "--state-stock",
        str(sstock_path),
        "--national-stock",
        str(nstock_path),
        "--horizon",
        "1",
    ]

    completed = subprocess.run(cmd, cwd=str(ROOT / "core_engine"), text=True, capture_output=True)
    if completed.returncode != 0:
        return {
            "name": s["name"],
            "ok": False,
            "error": completed.stderr or completed.stdout,
        }

    alloc_df = pd.read_csv(OUTPUT_DIR / "allocation_x.csv") if (OUTPUT_DIR / "allocation_x.csv").exists() else pd.DataFrame()
    unmet_df = pd.read_csv(OUTPUT_DIR / "unmet_demand_u.csv") if (OUTPUT_DIR / "unmet_demand_u.csv").exists() else pd.DataFrame()
    ship_df = pd.read_csv(OUTPUT_DIR / "shipment_plan.csv") if (OUTPUT_DIR / "shipment_plan.csv").exists() else pd.DataFrame()

    district_alloc = alloc_df[(alloc_df.get("supply_level", "") == "district") & (alloc_df.get("district_code", "").astype(str) == "1")]
    state_alloc = alloc_df[alloc_df.get("supply_level", "") == "state"]
    national_alloc = alloc_df[alloc_df.get("supply_level", "") == "national"]
    state_ship = ship_df[ship_df.get("from_district", "").astype(str).str.startswith("STATE::")]
    national_ship = ship_df[ship_df.get("from_district", "").astype(str) == "NATIONAL"]

    summary = {
        "name": s["name"],
        "ok": True,
        "allocated_total": _sum_col(alloc_df, "allocated_quantity"),
        "unmet_total": _sum_col(unmet_df, "unmet_quantity"),
        "district_alloc_total": _sum_col(district_alloc, "allocated_quantity"),
        "state_in_total": (_sum_col(state_alloc, "allocated_quantity") + _sum_col(state_ship, "quantity")),
        "national_in_total": (_sum_col(national_alloc, "allocated_quantity") + _sum_col(national_ship, "quantity")),
        "alloc_rows": int(len(alloc_df.index)),
        "unmet_rows": int(len(unmet_df.index)),
        "shipment_rows": int(len(ship_df.index)),
    }

    for suffix in ["allocation_x.csv", "unmet_demand_u.csv", "shipment_plan.csv", "inventory_t.csv", "run_summary.json"]:
        src = OUTPUT_DIR / suffix
        if src.exists():
            shutil.copyfile(src, SCENARIO_DIR / f"{s['name']}_{suffix}")

    exp = s["expected"]
    summary["meets_expected"] = bool(
        abs(summary["allocated_total"] - exp["allocated_total"]) <= 1e-9
        and abs(summary["unmet_total"] - exp["unmet_total"]) <= 1e-9
        and summary["district_alloc_total"] >= exp["district_alloc_min"]
        and summary["state_in_total"] >= exp["state_in_min"]
        and summary["national_in_total"] >= exp["national_in_min"]
    )
    return summary


def main() -> None:
    results = [run_one(s) for s in SCENARIOS]
    out = {
        "results": results,
        "all_passed": all(bool(r.get("meets_expected")) for r in results if r.get("ok")),
    }
    out_path = SCENARIO_DIR / "solver_validation_summary.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
