import pandas as pd
from pathlib import Path

OUT_DIR = Path("phase4/scenarios/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------------
# PARAMETERS
# -------------------------------
TARGET_STATE_CODE = "33"
NUM_DISTRICTS = 5
DEMAND_MULTIPLIER = 8.0
STATE_STOCK_SCALING = 0.1   # 10% of normal → collapse

# -------------------------------
# Load base demand
# -------------------------------
demand = pd.read_csv(
    "phase3/output/district_resource_demand.csv"
)

districts = pd.read_csv(
    "data/processed/new_data/clean_district_codes.csv"
)

state_districts = districts[
    districts["state_code"].astype(str) == TARGET_STATE_CODE
].head(NUM_DISTRICTS)

target_districts = state_districts["district_code"].tolist()

print("Target districts:", target_districts)

# -------------------------------
# Zero demand everywhere
# -------------------------------
demand["demand"] = 0.0

# -------------------------------
# Apply strong surge
# -------------------------------
mask = demand["district_code"].isin(target_districts)
demand.loc[mask, "demand"] = (
    demand.loc[mask, "demand"].replace(0, 1) * DEMAND_MULTIPLIER
)

# -------------------------------
# Write demand override
# -------------------------------
demand_out = OUT_DIR / "district_resource_demand_S5_state_collapse.csv"
demand.to_csv(demand_out, index=False)

# -------------------------------
# Collapse state stock
# -------------------------------
state_stock = pd.read_csv(
    "phase4/resources/synthetic_data/state_resource_stock.csv"
)

state_stock = state_stock[
    state_stock["state_code"].astype(str) == TARGET_STATE_CODE
]

state_stock["quantity"] = state_stock["quantity"] * STATE_STOCK_SCALING

state_out = OUT_DIR / "state_resource_stock_S5_state_collapse.csv"
state_stock.to_csv(state_out, index=False)

print("S5 SCENARIO GENERATED — STATE COLLAPSE → NATIONAL ESCALATION")
print("Demand file:", demand_out.resolve())
print("State stock override:", state_out.resolve())
print("Total demand:", demand["demand"].sum())
