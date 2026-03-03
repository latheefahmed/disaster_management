import pandas as pd
from pathlib import Path
import numpy as np

SCENARIO_ID = "S6"   # <<< change per run

ROOT = Path(".")
OUT_DIR = ROOT / "phase4" / "optimization" / "summary"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_PATH = OUT_DIR / "scenario_summary.csv"

ALLOC_PATH = ROOT / "phase4" / "optimization" / "output" / "allocation_x.csv"
UNMET_PATH = ROOT / "phase4" / "optimization" / "output" / "unmet_demand_u.csv"
DEMAND_PATH = ROOT / "phase3" / "output" / "district_resource_demand.csv"
POP_PATH = ROOT / "data" / "processed" / "new_data" / "clean_district_population.csv"

# ----------------------------
# SAFE CSV READERS
# ----------------------------
from pandas.errors import EmptyDataError

def safe_read_csv(path, columns):
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        df = pd.read_csv(path)
        if df.empty:
            return pd.DataFrame(columns=columns)
        return df
    except EmptyDataError:
        return pd.DataFrame(columns=columns)

alloc = safe_read_csv(
    ALLOC_PATH,
    ["supply_level", "resource_id", "state_code", "district_code", "time", "allocated_quantity"]
)

unmet = safe_read_csv(
    UNMET_PATH,
    ["resource_id", "district_code", "time", "unmet_demand"]
)

demand = pd.read_csv(DEMAND_PATH)
pop = pd.read_csv(POP_PATH)[["district_code", "population"]]

# ----------------------------
# AGGREGATES (SAFE)
# ----------------------------
total_demand = demand["demand"].sum()

total_alloc = alloc["allocated_quantity"].sum() if not alloc.empty else 0.0
total_unmet = unmet["unmet_demand"].sum() if not unmet.empty else 0.0

district_used = alloc.loc[alloc.supply_level == "district", "allocated_quantity"].sum() if not alloc.empty else 0.0
state_used = alloc.loc[alloc.supply_level == "state", "allocated_quantity"].sum() if not alloc.empty else 0.0
national_used = alloc.loc[alloc.supply_level == "national", "allocated_quantity"].sum() if not alloc.empty else 0.0

if national_used > 0:
    escalation = "national"
elif state_used > 0:
    escalation = "state"
else:
    escalation = "district"

# ----------------------------
# WORST-HIT DISTRICT (SAFE)
# ----------------------------
if not unmet.empty:
    unmet_by_district = unmet.groupby("district_code", as_index=False)["unmet_demand"].sum()
    worst = unmet_by_district.sort_values("unmet_demand", ascending=False).iloc[0]
    worst_district = worst["district_code"]
    worst_value = float(worst["unmet_demand"])
else:
    worst_district = None
    worst_value = 0.0

# ----------------------------
# FAIRNESS (SAFE)
# ----------------------------
if not alloc.empty:
    alloc_pc = (
        alloc.groupby("district_code", as_index=False)["allocated_quantity"].sum()
        .merge(pop, on="district_code", how="left")
    )
    alloc_pc["per_capita"] = alloc_pc["allocated_quantity"] / alloc_pc["population"]
    mean_pc = alloc_pc["per_capita"].mean()
    std_pc = alloc_pc["per_capita"].std()
    fairness_cv = float(std_pc / mean_pc) if mean_pc > 0 and np.isfinite(std_pc) else 0.0
else:
    fairness_cv = 0.0

# ----------------------------
# STATUS
# ----------------------------
if total_unmet == 0:
    status = "OK"
elif national_used > 0:
    status = "ESCALATED"
else:
    status = "FAILURE"

row = {
    "scenario_id": SCENARIO_ID,
    "total_demand": float(total_demand),
    "total_allocated": float(total_alloc),
    "total_unmet": float(total_unmet),
    "unmet_pct": float(total_unmet / total_demand) if total_demand > 0 else 0.0,
    "district_supply_used": float(district_used),
    "state_supply_used": float(state_used),
    "national_supply_used": float(national_used),
    "national_used_flag": int(national_used > 0),
    "escalation_level": escalation,
    "worst_hit_district": worst_district,
    "max_unmet_value": worst_value,
    "fairness_cv": fairness_cv,
    "status": status
}

df_new = pd.DataFrame([row])

if OUT_PATH.exists() and OUT_PATH.stat().st_size > 0:
    df_old = pd.read_csv(OUT_PATH)
    df_final = pd.concat([df_old, df_new], ignore_index=True)
else:
    df_final = df_new

df_final.to_csv(OUT_PATH, index=False)

print(f"Scenario {SCENARIO_ID} recorded successfully → {OUT_PATH}")
