import pandas as pd
from pathlib import Path

OUT_DIR = Path("phase4/scenarios/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------------
# PARAMETERS
# -------------------------------
TARGET_STATE_CODE = "33"
NUM_DISTRICTS = 5
DEMAND_MULTIPLIER = 15.0
STOCK_SCALING = 0.05   # 5% everywhere → guaranteed failure

# -------------------------------
# Load demand and districts
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
# Massive demand surge
# -------------------------------
mask = demand["district_code"].isin(target_districts)
demand.loc[mask, "demand"] = (
    demand.loc[mask, "demand"].replace(0, 1) * DEMAND_MULTIPLIER
)

demand_out = OUT_DIR / "district_resource_demand_S12_total_failure.csv"
demand.to_csv(demand_out, index=False)

# -------------------------------
# Collapse all stocks
# -------------------------------
district_stock = pd.read_csv(
    "phase4/resources/synthetic_data/district_resource_stock.csv"
)
state_stock = pd.read_csv(
    "phase4/resources/synthetic_data/state_resource_stock.csv"
)
national_stock = pd.read_csv(
    "phase4/resources/synthetic_data/national_resource_stock.csv"
)

district_stock["quantity"] *= STOCK_SCALING
state_stock["quantity"] *= STOCK_SCALING
national_stock["quantity"] *= STOCK_SCALING

district_out = OUT_DIR / "district_resource_stock_S12_total_failure.csv"
state_out = OUT_DIR / "state_resource_stock_S12_total_failure.csv"
national_out = OUT_DIR / "national_resource_stock_S12_total_failure.csv"

district_stock.to_csv(district_out, index=False)
state_stock.to_csv(state_out, index=False)
national_stock.to_csv(national_out, index=False)

print("S12 SCENARIO GENERATED — TOTAL FAILURE TRANSPARENCY")
print("Demand:", demand_out.resolve())
print("District stock:", district_out.resolve())
print("State stock:", state_out.resolve())
print("National stock:", national_out.resolve())
print("Total demand:", demand["demand"].sum())