import pandas as pd
from pathlib import Path

OUT_DIR = Path("phase4/scenarios/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Resources that experience asymmetric failure
FAILED_RESOURCES = {"R6", "R11"}

# Severity parameters (DESIGNED to force escalation)
ALPHA_STATE_FAIL = 0.05
ALPHA_NATIONAL_FAIL = 0.02

# Load demand
demand = pd.read_csv("phase3/output/district_resource_demand.csv")

# Peak demand per resource (time-consistent)
peak = (
    demand
    .groupby(["resource_id", "time"])["demand"]
    .sum()
    .groupby("resource_id")
    .max()
)

# Load baseline stocks
state = pd.read_csv(
    "phase4/resources/synthetic_data/state_resource_stock.csv"
)
national = pd.read_csv(
    "phase4/resources/synthetic_data/national_resource_stock.csv"
)

# Apply asymmetric failure
def adjust_state(row):
    if row["resource_id"] in FAILED_RESOURCES:
        return ALPHA_STATE_FAIL * peak[row["resource_id"]]
    return row["quantity"]

def adjust_national(row):
    if row["resource_id"] in FAILED_RESOURCES:
        return ALPHA_NATIONAL_FAIL * peak[row["resource_id"]]
    return row["quantity"]

state["quantity"] = state.apply(adjust_state, axis=1)
national["quantity"] = national.apply(adjust_national, axis=1)

# Write outputs
state_out = OUT_DIR / "state_resource_stock_C5.csv"
nat_out = OUT_DIR / "national_resource_stock_C5.csv"

state.to_csv(state_out, index=False)
national.to_csv(nat_out, index=False)

print("SCENARIO C5 GENERATED")
print("Failed resources:", FAILED_RESOURCES)
print("State alpha (failed):", ALPHA_STATE_FAIL)
print("National alpha (failed):", ALPHA_NATIONAL_FAIL)
print("Outputs:")
print(state_out.resolve())
print(nat_out.resolve())
