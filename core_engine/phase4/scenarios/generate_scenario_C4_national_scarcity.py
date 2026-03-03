import pandas as pd
from pathlib import Path

OUT_DIR = Path("phase4/scenarios/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ALPHA_STATE = 0.2
ALPHA_NATIONAL = 0.1

demand = pd.read_csv("phase3/output/district_resource_demand.csv")
peak = (
    demand
    .groupby(["resource_id", "time"])["demand"]
    .sum()
    .groupby("resource_id")
    .max()
)


state = pd.read_csv(
    "phase4/resources/synthetic_data/state_resource_stock.csv"
)
national = pd.read_csv(
    "phase4/resources/synthetic_data/national_resource_stock.csv"
)

state["quantity"] = state["resource_id"].map(
    lambda r: ALPHA_STATE * peak[r]
)

national["quantity"] = national["resource_id"].map(
    lambda r: ALPHA_NATIONAL * peak[r]
)

state_out = OUT_DIR / "state_resource_stock_C4.csv"
nat_out = OUT_DIR / "national_resource_stock_C4.csv"

state.to_csv(state_out, index=False)
national.to_csv(nat_out, index=False)

print("SCENARIO C4 GENERATED")
print("State alpha:", ALPHA_STATE)
print("National alpha:", ALPHA_NATIONAL)
print("Outputs:")
print(state_out.resolve())
print(nat_out.resolve())
