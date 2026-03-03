import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEMAND_PATH = ROOT / "phase4/scenarios/generated/scenario_A_demand_shock.csv"
STATE_STOCK_IN = ROOT / "phase4/resources/synthetic_data/state_resource_stock.csv"
OUT_DIR = ROOT / "phase4/scenarios/generated"
OUT_PATH = OUT_DIR / "state_resource_stock_C2.csv"

ALPHA = 0.8

OUT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    demand_raw = pd.read_csv(DEMAND_PATH)

    required = {"resource_id", "district_code", "time", "demand"}
    missing = required - set(demand_raw.columns)
    if missing:
        raise ValueError(f"Demand missing columns: {missing}")

    demand = demand_raw[["resource_id", "district_code", "time", "demand"]].copy()

    # Peak demand per resource across time
    peak_demand = (
        demand
        .groupby(["resource_id", "time"], as_index=False)["demand"]
        .sum()
        .groupby("resource_id", as_index=False)["demand"]
        .max()
        .rename(columns={"demand": "peak_demand"})
    )

    state_stock = pd.read_csv(STATE_STOCK_IN)

    if set(state_stock.columns) != {"state_code", "resource_id", "quantity"}:
        raise ValueError("State stock schema mismatch")

    # Original totals for proportional redistribution
    orig_totals = (
        state_stock.groupby("resource_id", as_index=False)["quantity"]
        .sum()
        .rename(columns={"quantity": "orig_total"})
    )

    merged = (
        state_stock
        .merge(orig_totals, on="resource_id", how="left")
        .merge(peak_demand, on="resource_id", how="left")
    )

    if merged["peak_demand"].isna().any():
        raise ValueError("Some resources have no demand")

    merged["target_total_stock"] = ALPHA * merged["peak_demand"]

    # Redistribute proportionally across states
    merged["quantity"] = (
        merged["quantity"] / merged["orig_total"]
        * merged["target_total_stock"]
    )

    merged = merged[["state_code", "resource_id", "quantity"]]
    merged["quantity"] = merged["quantity"].round(6)

    merged.to_csv(OUT_PATH, index=False)

    print("Scenario C2 state stock generated successfully")
    print("Path:", OUT_PATH)
    print("Alpha:", ALPHA)

if __name__ == "__main__":
    main()
