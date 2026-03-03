import pandas as pd
from pathlib import Path

OUT_DIR = Path("phase4/scenarios/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------------
# C6: MULTI-STATE REGIONAL ESCALATION
# -------------------------------

# Include Tamil Nadu + synthetic regional copies
C6_STATE_CODES = ["33", "1", "2", "3", "4", "5"]

ALPHA_STATE = 0.15
ALPHA_NATIONAL = 0.08

# -------------------------------
# Load base demand (Tamil Nadu)
# -------------------------------
demand = pd.read_csv("phase3/output/district_resource_demand.csv")

districts = pd.read_csv(
    "data/processed/new_data/clean_district_codes.csv"
)

tn_districts = districts[districts["state_code"].astype(str) == "33"]

demand = demand.merge(
    tn_districts[["district_code"]],
    on="district_code",
    how="inner"
)

# -------------------------------
# Replicate demand to other states
# -------------------------------
replicated = []

for s in C6_STATE_CODES:
    if s == "33":
        d = demand.copy()
        d["state_code"] = s
        replicated.append(d)
    else:
        # clone demand but map to districts of that state
        sd = districts[districts["state_code"].astype(str) == s]
        if sd.empty:
            continue

        d = demand.copy()
        d = d.sample(n=min(len(d), len(sd)), replace=True, random_state=42)
        d["district_code"] = sd["district_code"].values[:len(d)]
        d["state_code"] = s
        replicated.append(d)

full_demand = pd.concat(replicated, ignore_index=True)

# -------------------------------
# Peak regional demand
# -------------------------------
peak = (
    full_demand
    .groupby(["resource_id", "time"])["demand"]
    .sum()
    .groupby("resource_id")
    .max()
)

# -------------------------------
# Load baseline stocks
# -------------------------------
state = pd.read_csv(
    "phase4/resources/synthetic_data/state_resource_stock.csv"
)
national = pd.read_csv(
    "phase4/resources/synthetic_data/national_resource_stock.csv"
)

state = state[state["state_code"].astype(str).isin(C6_STATE_CODES)]

# -------------------------------
# Apply scarcity
# -------------------------------
state["quantity"] = state["resource_id"].map(
    lambda r: ALPHA_STATE * peak[r]
)

national["quantity"] = national["resource_id"].map(
    lambda r: ALPHA_NATIONAL * peak[r]
)

# -------------------------------
# Write outputs
# -------------------------------
state_out = OUT_DIR / "state_resource_stock_C6.csv"
nat_out = OUT_DIR / "national_resource_stock_C6.csv"

state.to_csv(state_out, index=False)
national.to_csv(nat_out, index=False)

print("SCENARIO C6 GENERATED — MULTI-STATE REGIONAL ESCALATION")
print("States:", C6_STATE_CODES)
print("Peak demand (sample):")
print(peak.head())
print("Outputs:")
print(state_out.resolve())
print(nat_out.resolve())
