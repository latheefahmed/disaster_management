import json
import time
from datetime import datetime, UTC
from pathlib import Path

import requests

API = "http://127.0.0.1:8004"
LEVELS = [
    ("extremely_low", 0.20),
    ("low", 0.40),
    ("medium_low", 0.70),
    ("medium", 1.00),
    ("medium_high", 1.25),
    ("high", 1.50),
    ("extremely_high", 1.79),
]


def req(method: str, url: str, headers=None, payload=None, timeout=180):
    if method == "GET":
        r = requests.get(url, headers=headers, timeout=timeout)
    else:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def approximately(a: float, b: float, eps: float = 0.03) -> bool:
    return abs(float(a) - float(b)) <= eps


def main():
    login = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin123"}, timeout=30)
    login.raise_for_status()
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    states = req("GET", f"{API}/metadata/states", headers=headers, timeout=30)
    districts = req("GET", f"{API}/metadata/districts", headers=headers, timeout=30)
    resources = req("GET", f"{API}/metadata/resources", headers=headers, timeout=30)

    if not states or not districts or not resources:
        raise RuntimeError("metadata insufficient for validation")

    state_code = str(states[0]["state_code"])
    districts_in_state = [str(d["district_code"]) for d in districts if str(d.get("state_code")) == state_code]
    selected_districts = districts_in_state[:6] if len(districts_in_state) >= 6 else districts_in_state
    selected_resources = [str(r["resource_id"]) for r in resources[:6]]

    if not selected_districts or not selected_resources:
        raise RuntimeError("unable to build selected district/resource scope")

    case_rows = []

    for idx, (level, expected_ratio) in enumerate(LEVELS, start=1):
        scenario = req("POST", f"{API}/admin/scenarios", headers=headers, payload={"name": f"INTENSITY_VALID_{level}_{int(time.time())}"}, timeout=30)
        scenario_id = int(scenario["id"])
        seed = 20260304 + idx

        payload = {
            "preset": level,
            "seed": seed,
            "time_horizon": 4,
            "stress_mode": level in {"high", "extremely_high"},
            "state_codes": [state_code],
            "district_codes": selected_districts,
            "resource_ids": selected_resources,
            "quantity_mode": "stock_aware",
            "stock_aware_distribution": True,
            "replace_existing": False,
        }

        preview_a = req("POST", f"{API}/admin/scenarios/{scenario_id}/randomizer/preview", headers=headers, payload=payload, timeout=120)
        preview_b = req("POST", f"{API}/admin/scenarios/{scenario_id}/randomizer/preview", headers=headers, payload=payload, timeout=120)

        deterministic_preview_ok = (
            int(preview_a.get("row_count") or 0) == int(preview_b.get("row_count") or 0)
            and float(preview_a.get("total_generated_demand") or 0.0) == float(preview_b.get("total_generated_demand") or 0.0)
            and float(preview_a.get("total_available_supply") or 0.0) == float(preview_b.get("total_available_supply") or 0.0)
        )

        req("POST", f"{API}/admin/scenarios/{scenario_id}/randomizer/apply", headers=headers, payload=payload, timeout=120)
        run_resp = requests.post(f"{API}/admin/scenarios/{scenario_id}/run", headers=headers, json={"scope_mode": "focused"}, timeout=300)
        run_resp.raise_for_status()

        runs = req("GET", f"{API}/admin/scenarios/{scenario_id}/runs", headers=headers, timeout=90)
        run_id = int(runs[0]["id"])
        summary = req("GET", f"{API}/admin/scenarios/{scenario_id}/runs/{run_id}/summary", headers=headers, timeout=120)

        totals = summary.get("totals", {})
        allocated = float(totals.get("allocated_quantity") or 0.0)
        unmet = float(totals.get("unmet_quantity") or 0.0)
        demand = allocated + unmet
        service_ratio = (allocated / demand) if demand > 1e-9 else 0.0

        source_alloc = (summary.get("source_scope_breakdown", {}) or {}).get("allocations", {})
        state_alloc = float(source_alloc.get("state") or 0.0)
        neighbor_alloc = float(source_alloc.get("neighbor_state") or 0.0)
        national_alloc = float(source_alloc.get("national") or 0.0)

        ratio_ok = approximately(float(preview_a.get("demand_supply_ratio") or 0.0), expected_ratio, eps=0.03)
        expected_shortage = float(preview_a.get("expected_shortage_estimate") or 0.0)

        checks = {
            "deterministic_preview_ok": deterministic_preview_ok,
            "ratio_matches_level": ratio_ok,
            "extremely_low_surplus": True,
            "medium_balanced": True,
            "medium_high_state_usage": True,
            "high_national_usage": True,
            "extremely_high_unmet": True,
        }

        if level == "extremely_low":
            checks["extremely_low_surplus"] = unmet <= 1e-6 and expected_shortage <= 1e-6
        if level == "medium":
            checks["medium_balanced"] = service_ratio >= 0.95
        if level == "medium_high":
            checks["medium_high_state_usage"] = bool(summary.get("used_state_stock")) or state_alloc > 1e-6 or neighbor_alloc > 1e-6
        if level == "high":
            checks["high_national_usage"] = bool(summary.get("used_national_stock")) or national_alloc > 1e-6
        if level == "extremely_high":
            checks["extremely_high_unmet"] = unmet > 1e-6

        case_ok = all(v for v in checks.values())

        case_rows.append(
            {
                "level": level,
                "scenario_id": scenario_id,
                "run_id": run_id,
                "preview_demand_supply_ratio": float(preview_a.get("demand_supply_ratio") or 0.0),
                "expected_ratio": expected_ratio,
                "total_available_supply": float(preview_a.get("total_available_supply") or 0.0),
                "total_generated_demand": float(preview_a.get("total_generated_demand") or 0.0),
                "expected_shortage_estimate": expected_shortage,
                "allocated": allocated,
                "unmet": unmet,
                "service_ratio": service_ratio,
                "state_alloc": state_alloc,
                "neighbor_alloc": neighbor_alloc,
                "national_alloc": national_alloc,
                "used_state_stock": bool(summary.get("used_state_stock")),
                "used_national_stock": bool(summary.get("used_national_stock")),
                "escalation_status": summary.get("escalation_status") or {},
                "checks": checks,
                "pass": case_ok,
            }
        )

    passed = sum(1 for row in case_rows if row.get("pass"))
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "levels": len(case_rows),
        "passed": passed,
        "failed": len(case_rows) - passed,
        "rows": case_rows,
    }

    out_json = Path("RANDOMIZER_INTENSITY_LADDER_VALIDATION_2026-03-04.json")
    out_md = Path("RANDOMIZER_INTENSITY_LADDER_VALIDATION_2026-03-04.md")
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Randomizer Intensity Ladder Validation (2026-03-04)",
        "",
        f"- Levels tested: {report['levels']}",
        f"- Passed: {report['passed']}",
        f"- Failed: {report['failed']}",
        "",
        "| Level | Scenario | Run | Ratio(actual/expected) | Supply | Demand | Unmet | StateUsed | NationalUsed | NeighborAlloc | Pass |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|---:|---|",
    ]
    for row in case_rows:
        lines.append(
            f"| {row['level']} | {row['scenario_id']} | {row['run_id']} | {row['preview_demand_supply_ratio']:.3f}/{row['expected_ratio']:.2f} | {row['total_available_supply']:.2f} | {row['total_generated_demand']:.2f} | {row['unmet']:.2f} | {row['used_state_stock']} | {row['used_national_stock']} | {row['neighbor_alloc']:.2f} | {'PASS' if row['pass'] else 'FAIL'} |"
        )

    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"json_report": str(out_json.resolve()), "md_report": str(out_md.resolve()), "passed": passed, "failed": len(case_rows)-passed}, indent=2))


if __name__ == "__main__":
    main()
