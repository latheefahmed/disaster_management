import pandas as pd
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEMAND_PATH = ROOT / "phase3/output/district_resource_demand.csv"
CONFIG_PATH = ROOT / "phase4/scenarios/config/scenario_A_demand_shock.yaml"
OUT_DIR = ROOT / "phase4/scenarios/generated"

OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

def validate_demand_schema(df):
    expected = {"resource_id", "district_code", "time", "demand"}
    if set(df.columns) != expected:
        raise ValueError(f"Demand schema mismatch. Found {df.columns}")

def generate_scenario():
    cfg = load_config()
    df = pd.read_csv(DEMAND_PATH)

    validate_demand_schema(df)

    agg = (
        df.groupby("district_code", as_index=False)["demand"]
        .sum()
        .sort_values("demand", ascending=False)
    )

    k = cfg["affected"]["k"]
    impacted_districts = agg.head(k)["district_code"].tolist()

    df["scenario_demand"] = df["demand"]

    mask = df["district_code"].isin(impacted_districts)
    df.loc[mask, "scenario_demand"] = (
        df.loc[mask, "demand"] * cfg["multiplier"]
    )

    out = df.rename(columns={"scenario_demand": "demand"})[
        ["resource_id", "district_code", "time", "demand"]
    ]

    out_path = OUT_DIR / f"{cfg['scenario_name']}.csv"

    if out_path.exists() and not cfg["output"]["overwrite"]:
        raise FileExistsError(f"{out_path} already exists")

    out.to_csv(out_path, index=False)
    print(f"Scenario generated at: {out_path}")

if __name__ == "__main__":
    generate_scenario()