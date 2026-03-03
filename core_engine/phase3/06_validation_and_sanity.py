from pathlib import Path
import pickle
import numpy as np

base = Path(__file__).resolve().parents[1]
models = base / "models"

def assert_range(series, lo, hi, name):
    if not ((series >= lo) & (series <= hi)).all():
        raise ValueError(f"{name} out of bounds")

def run():
    with open(models / "severity" / "severity_model.pkl", "rb") as f:
        sev = pickle.load(f)

    with open(models / "vulnerability" / "vulnerability_composite.pkl", "rb") as f:
        vul = pickle.load(f)

    with open(models / "exposure_capacity.pkl", "rb") as f:
        expcap = pickle.load(f)

    with open(models / "ai_assisted_demand.pkl", "rb") as f:
        dem = pickle.load(f)

    assert_range(sev["severity_score"], 0, 1, "Severity")
    assert_range(vul["vulnerability_score"], 0, 1, "Vulnerability")
    assert_range(expcap["exposure_score"], 0, 1, "Exposure")
    assert_range(expcap["capacity_score"], 0, 1, "Capacity")

    merged = (
        dem
        .merge(sev, on=["district_code", "time_step"])
        .merge(vul, on="district_code")
        .merge(expcap, on="district_code")
    )

    if merged.isna().any().any():
        raise ValueError("Missing values after merge")

    if (merged["raw_demand"] < 0).any():
        raise ValueError("Negative demand detected")

    print("ALL PHASE 3 VALIDATION CHECKS PASSED")

if __name__ == "__main__":
    run()
