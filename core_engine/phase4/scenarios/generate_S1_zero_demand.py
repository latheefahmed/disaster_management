import pandas as pd
from pathlib import Path

OUT_DIR = Path("phase4/scenarios/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------------
# Load base demand
# -------------------------------
demand = pd.read_csv(
    "phase3/output/district_resource_demand.csv"
)

# -------------------------------
# Zero out demand
# -------------------------------
demand["demand"] = 0.0

# -------------------------------
# Write scenario demand
# -------------------------------
out_path = OUT_DIR / "district_resource_demand_S1_zero.csv"
demand.to_csv(out_path, index=False)

print("S1 SCENARIO GENERATED — ZERO DEMAND BASELINE")
print("Output:", out_path.resolve())
print("Rows:", len(demand))
print("Total demand:", demand["demand"].sum())
