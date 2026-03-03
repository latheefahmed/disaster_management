import pandas as pd

demand = pd.read_csv("phase4/scenarios/generated/scenario_A_demand_shock.csv")
state_stock = pd.read_csv("phase4/scenarios/generated/state_resource_stock_B1.csv")

demand_sum = (
    demand.groupby("resource_id")["demand"]
    .sum()
    .reset_index(name="total_demand")
)

stock_sum = (
    state_stock.groupby("resource_id")["quantity"]
    .sum()
    .reset_index(name="total_state_stock")
)

merged = demand_sum.merge(stock_sum, on="resource_id", how="left")
merged["slack"] = merged["total_state_stock"] - merged["total_demand"]

print(merged)