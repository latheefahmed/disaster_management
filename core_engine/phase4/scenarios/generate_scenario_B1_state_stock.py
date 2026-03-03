import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

IN_PATH = ROOT / "phase4/resources/synthetic_data/state_resource_stock.csv"
OUT_DIR = ROOT / "phase4/scenarios/generated"
OUT_PATH = OUT_DIR / "state_resource_stock_B1.csv"

REDUCTION_FACTOR = 0.5  # 50% reduction

OUT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    df = pd.read_csv(IN_PATH)

    expected_cols = {"state_code", "resource_id", "quantity"}
    if set(df.columns) != expected_cols:
        raise ValueError(f"Schema mismatch: {df.columns}")

    df["quantity"] = (df["quantity"] * REDUCTION_FACTOR).round(2)

    df.to_csv(OUT_PATH, index=False)

    print("Scenario B1 state stock generated:")
    print(OUT_PATH)

if __name__ == "__main__":
    main()
