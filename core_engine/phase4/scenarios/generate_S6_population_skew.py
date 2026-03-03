import pandas as pd
from pathlib import Path

OUT_DIR = Path("phase4/scenarios/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------------
# PARAMETERS
# -------------------------------
TARGET_STATE_CODE = "33"
NUM_SMALL_DISTRICTS = 4
LARGE_DISTRICT_MULTIPLIER = 6.0
SMALL_DISTRICT_MULTIPLIER = 2.0

# -------------------------------
# Load data
# -------------------------------
demand = pd.read_csv(
    "phase3/output/district_resource_demand.csv"
)

districts = pd.read_csv(
    "data/processed/new_data/clean_district_codes.csv"
)

population = pd.read_csv(
    "data/processed/new_data/clean_district_population.csv"
)

# -------------------------------
# Filter to state
# -------------------------------
state_pop = population[
    population["state_code"].astype(str) == TARGET_STATE_CODE
]

# -------------------------------
# Select districts
# -------------------------------
largest = (
    state_pop.sort_values("population", ascending=False)
    .iloc[0]["district_code"]
)

smallest = (
    state_pop.sort_values("population", ascending=True)
    .head(NUM_SMALL_DISTRICTS)["district_code"]
    .tolist()
)

target_districts = [largest] + smallest

print("Large district:", largest)
print("Small districts:", smallest)

# -------------------------------
# Zero demand everywhere
# -------------------------------
demand["demand"] = 0.0

# -------------------------------
# Apply skewed demand
# -------------------------------
for d in target_districts:
    if d == largest:
        mult = LARGE_DISTRICT_MULTIPLIER
    else:
        mult = SMALL_DISTRICT_MULTIPLIER

    mask = demand["district_code"] == d
    demand.loc[mask, "demand"] = (
        demand.loc[mask, "demand"].replace(0, 1) * mult
    )

# -------------------------------
# Write scenario
# -------------------------------
out_path = OUT_DIR / "district_resource_demand_S6_population_skew.csv"
demand.to_csv(out_path, index=False)

print("S6 SCENARIO GENERATED — POPULATION SKEW FAIRNESS")
print("Districts tested:", target_districts)
print("Total demand:", demand["demand"].sum())
print("Output:", out_path.resolve())
