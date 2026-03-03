import pandas as pd
from pathlib import Path

OUT_DIR = Path("phase4/scenarios/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------------
# PARAMETERS
# -------------------------------
TARGET_STATE_CODE = "33"          # Tamil Nadu
TARGET_DISTRICT_CODE = None       # auto-pick first district
DEMAND_MULTIPLIER = 5.0           # shock intensity

# -------------------------------
# Load base demand
# -------------------------------
demand = pd.read_csv(
    "phase3/output/district_resource_demand.csv"
)

districts = pd.read_csv(
    "data/processed/new_data/clean_district_codes.csv"
)

# -------------------------------
# Select one district
# -------------------------------
state_districts = districts[
    districts["state_code"].astype(str) == TARGET_STATE_CODE
]

if TARGET_DISTRICT_CODE is None:
    TARGET_DISTRICT_CODE = state_districts.iloc[0]["district_code"]

print("Target district:", TARGET_DISTRICT_CODE)

# -------------------------------
# Zero demand everywhere
# -------------------------------
demand["demand"] = 0.0

# -------------------------------
# Apply shock to target district
# -------------------------------
mask = demand["district_code"] == TARGET_DISTRICT_CODE
demand.loc[mask, "demand"] = (
    demand.loc[mask, "demand"].replace(0, 1) * DEMAND_MULTIPLIER
)

# NOTE:
# If original demand was already non-zero, multiplier amplifies it.
# If zero, this creates a minimal but non-zero shock.

# -------------------------------
# Write scenario demand
# -------------------------------
out_path = OUT_DIR / "district_resource_demand_S3_single_district.csv"
demand.to_csv(out_path, index=False)

print("S3 SCENARIO GENERATED — SINGLE DISTRICT SHOCK")
print("District:", TARGET_DISTRICT_CODE)
print("Total demand:", demand["demand"].sum())
print("Output:", out_path.resolve())