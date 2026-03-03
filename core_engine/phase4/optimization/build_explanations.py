import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "output")

ALLOC_PATH = os.path.join(OUT_DIR, "allocation_x.csv")
UNMET_PATH = os.path.join(OUT_DIR, "unmet_demand_u.csv")


def main():

    if not os.path.exists(ALLOC_PATH):
        raise FileNotFoundError("allocation_x.csv not found")

    if not os.path.exists(UNMET_PATH):
        raise FileNotFoundError("unmet_demand_u.csv not found")

    alloc = pd.read_csv(ALLOC_PATH)
    unmet = pd.read_csv(UNMET_PATH)

    # -------------------------
    # FIXED COLUMN NAME
    # -------------------------
    unmet_nonzero = unmet[unmet["unmet_quantity"] > 0]

    summary = (
        unmet_nonzero
        .groupby(["district_code", "resource_id"], as_index=False)
        .agg({"unmet_quantity": "sum"})
        .rename(columns={"unmet_quantity": "total_unmet"})
        .sort_values("total_unmet", ascending=False)
    )

    out_path = os.path.join(OUT_DIR, "explanations.csv")
    summary.to_csv(out_path, index=False)

    print("Written:", out_path)
    print("Rows:", len(summary))


if __name__ == "__main__":
    main()
