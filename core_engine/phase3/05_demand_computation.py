from pathlib import Path
import pickle
import pandas as pd
import numpy as np

base = Path(__file__).resolve().parents[1]
models = base / "models"

EPS = 1e-9

def run():
    with open(models / "severity" / "severity_model.pkl", "rb") as f:
        sev = pickle.load(f)

    with open(models / "vulnerability" / "vulnerability_composite.pkl", "rb") as f:
        vul = pickle.load(f)

    with open(models / "exposure_capacity.pkl", "rb") as f:
        expcap = pickle.load(f)

    df = (
        sev
        .merge(vul, on="district_code", how="inner")
        .merge(expcap, on="district_code", how="inner")
    )

    raw = (
        df["severity_score"] *
        df["vulnerability_score"] *
        df["exposure_score"] *
        (1.0 - df["capacity_score"])
    )

    raw = np.where(raw < EPS, 0.0, raw)

    out = df[["district_code", "time_step"]].copy()
    out["raw_demand"] = raw

    with open(models / "ai_assisted_demand.pkl", "wb") as f:
        pickle.dump(out, f)

def export_demand_table():
    import os
    from pathlib import Path
    import pandas as pd
    import pickle

    base = Path(__file__).resolve().parents[1]
    models = base / "models"

    with open(models / "ai_assisted_demand.pkl", "rb") as f:
        df = pickle.load(f)

    resource_df = pd.read_csv(
        base / "phase4" / "resources" / "schema" / "resource_catalog.csv"
    )

    rows = []

    for _, rrow in resource_df.iterrows():
        rid = rrow["resource_id"]
        priority = rrow["ethical_priority"]

        temp = df.copy()
        temp["resource_id"] = rid
        temp["demand"] = temp["raw_demand"] * priority

        rows.append(
            temp[[
                "resource_id",
                "district_code",
                "time_step",
                "demand"
            ]]
        )

    final = pd.concat(rows, ignore_index=True)

    final = final.rename(columns={"time_step": "time"})

    out_dir = base / "phase3" / "output"
    out_dir.mkdir(exist_ok=True)

    final.to_csv(
        out_dir / "district_resource_demand.csv",
        index=False
    )


if __name__ == "__main__":
    run()
    export_demand_table()
