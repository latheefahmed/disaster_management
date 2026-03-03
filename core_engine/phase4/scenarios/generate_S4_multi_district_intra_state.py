import pandas as pd
from pathlib import Path

OUT_DIR = Path("phase4/scenarios/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------------
# PARAMETERS
# -------------------------------
TARGET_STATE_CODE = "33"
NUM_DISTRICTS = 5
DEMAND_MULTIPLIER = 3.0

# -------------------------------
# Load data
# -------------------------------
demand = pd.read_csv(
    "phase3/output/district_resource_demand.csv"
)

districts = pd.read_csv(
    "data/processed/new_data/clean_district_codes.csv"
)

# -------------------------------
# Select districts in the state
# -------------------------------
state_districts = districts[
    districts["state_code"].astype(str) == TARGET_STATE_CODE
].head(NUM_DISTRICTS)

target_districts = state_districts["district_code"].tolist()

print("Target state:", TARGET_STATE_CODE)
print("Target districts:", target_districts)

# -------------------------------
# Zero demand everywhere
# -------------------------------
demand["demand"] = 0.0

# -------------------------------
# Apply surge to selected districts
# -------------------------------
mask = demand["district_code"].isin(target_districts)

demand.loc[mask, "demand"] = (
    demand.loc[mask, "demand"].replace(0, 1) * DEMAND_MULTIPLIER
)

# -------------------------------
# Write scenario demand
# -------------------------------
out_path = OUT_DIR / "district_resource_demand_S4_multi_district_state.csv"
demand.to_csv(out_path, index=False)

print("S4 SCENARIO GENERATED — MULTI-DISTRICT INTRA-STATE SURGE")
print("Total demand:", demand["demand"].sum())
print("Output:", out_path.resolve())
