import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
OPT_PATH = os.path.join(BASE_DIR, "optimization")
sys.path.append(OPT_PATH)

from loaders import (
    load_demand,
    load_district_stock,
    load_state_stock,
    load_national_stock
)


BASE_PATH = "."

print("\n===== LOADING DATA =====")

# -----------------------
# Demand
# -----------------------
demand_df = load_demand(BASE_PATH)
total_demand = demand_df["demand"].sum()

print("Total Demand:", total_demand)
print("Demand Rows:", len(demand_df))

# -----------------------
# District Stock
# -----------------------
district_stock_df = load_district_stock(BASE_PATH)
total_district_stock = district_stock_df["quantity"].sum()

print("Total District Stock:", total_district_stock)
print("District Stock Rows:", len(district_stock_df))

# -----------------------
# State Stock
# -----------------------
state_stock_df = load_state_stock(BASE_PATH)
total_state_stock = state_stock_df["quantity"].sum()

print("Total State Stock:", total_state_stock)
print("State Stock Rows:", len(state_stock_df))

# -----------------------
# National Stock
# -----------------------
national_stock_df = load_national_stock(BASE_PATH)
total_national_stock = national_stock_df["quantity"].sum()

print("Total National Stock:", total_national_stock)
print("National Stock Rows:", len(national_stock_df))

# -----------------------
# Combined Supply
# -----------------------
total_supply = (
    total_district_stock +
    total_state_stock +
    total_national_stock
)

print("\n===== SUMMARY =====")
print("Total Supply:", total_supply)
print("Supply / Demand Ratio:", total_supply / total_demand if total_demand > 0 else "∞")
