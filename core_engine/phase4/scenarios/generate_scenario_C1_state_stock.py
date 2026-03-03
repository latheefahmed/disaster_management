import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEMAND_PATH = ROOT / "phase4/scenarios/generated/scenario_A_demand_shock.csv"
STATE_STOCK_IN = ROOT / "phase4/resources/synthetic_data/state_resource_stock.csv"
OUT_DIR = ROOT / "phase4/scenarios/generated"
OUT_PATH = OUT_DIR / "state_resource_stock_C1.csv"

ALPHA = 0.8  # calibrated scarcity factor

OUT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    demand_raw = pd.read_csv(DEMAND_PATH)
    state_stock = pd.read_csv(STATE_STOCK_IN)

    required_demand_cols = {"resource_id", "district_code", "time", "demand"}
    missing = required_demand_cols - set(demand_raw.columns)
    if missing:
        raise ValueError(f"Demand file missing columns: {missing}")

    # Select only canonical demand columns
    demand = demand_raw[["resource_id", "district_code", "time", "demand"]].copy()

    required_stock_cols = {"state_code", "resource_id", "quantity"}
    if set(state_stock.columns) != required_stock_cols:
        raise ValueError("State stock schema mismatch")

    # Total demand per resource
    total_demand = (
        demand.groupby("resource_id", as_index=False)["demand"]
        .sum()
        .rename(columns={"demand": "total_demand"})
    )

    # Original state stock totals (for proportional scaling)
    state_totals = (
        state_stock.groupby("resource_id", as_index=False)["quantity"]
        .sum()
        .rename(columns={"quantity": "orig_total_stock"})
    )

    merged = (
        state_stock
        .merge(state_totals, on="resource_id", how="left")
        .merge(total_demand, on="resource_id", how="left")
    )

    if merged["total_demand"].isna().any():
        raise ValueError("Some resources in state stock have no demand")

    # Target calibrated stock
    merged["target_total_stock"] = ALPHA * merged["total_demand"]

    # Proportional redistribution across states
    merged["quantity"] = (
        merged["quantity"] / merged["orig_total_stock"]
        * merged["target_total_stock"]
    )

    merged = merged[["state_code", "resource_id", "quantity"]]
    merged["quantity"] = merged["quantity"].round(6)

    merged.to_csv(OUT_PATH, index=False)

    print("Scenario C1 state stock generated successfully")
    print("Path:", OUT_PATH)
    print("Alpha:", ALPHA)

if __name__ == "__main__":
    main()
