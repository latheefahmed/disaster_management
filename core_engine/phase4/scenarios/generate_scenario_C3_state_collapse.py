import pandas as pd
from pathlib import Path

OUT_DIR = Path("phase4/scenarios/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ALPHA_STATE = 0.6

demand = pd.read_csv("phase3/output/district_resource_demand.csv")
peak = (
    demand
    .groupby("resource_id")["demand"]
    .max()
)

state = pd.read_csv(
    "phase4/resources/synthetic_data/state_resource_stock.csv"
)

state["quantity"] = state["resource_id"].map(
    lambda r: ALPHA_STATE * peak[r]
)

out_path = OUT_DIR / "state_resource_stock_C3.csv"
state.to_csv(out_path, index=False)

print("SCENARIO C3 GENERATED")
print("State stock scaled to:", ALPHA_STATE)
print("Output:", out_path.resolve())
