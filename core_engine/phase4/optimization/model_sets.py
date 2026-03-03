import pandas as pd
from pathlib import Path


def load_sets(base_path=".", demand_override_path=None):

    # ============================================================
    # DEMAND
    # ============================================================

    if demand_override_path:
        demand_path = Path(demand_override_path)
    else:
        demand_path = (
            Path(base_path)
            / "phase3"
            / "output"
            / "district_resource_demand.csv"
        )

    df = pd.read_csv(demand_path)

    df["district_code"] = df["district_code"].astype(str)
    df["resource_id"] = df["resource_id"].astype(str)

    D = sorted(df["district_code"].unique().tolist())
    R = sorted(df["resource_id"].unique().tolist())
    T = sorted(df["time"].unique().tolist())

    # ============================================================
    # DISTRICT → STATE MAP  (FIXED SOURCE)
    # ============================================================

    map_path = (
        Path(base_path)
        / "data"
        / "processed"
        / "new_data"
        / "clean_district_codes.csv"
    )

    map_df = pd.read_csv(map_path)

    map_df["district_code"] = map_df["district_code"].astype(str)
    map_df["state_code"] = map_df["state_code"].astype(str)

    district_to_state = dict(
        zip(
            map_df["district_code"],
            map_df["state_code"]
        )
    )

    S = sorted(map_df["state_code"].unique().tolist())

    # L kept for compatibility
    L = ["district", "state", "national"]

    return D, S, R, L, T, district_to_state
