from pathlib import Path
import pandas as pd
import numpy as np
import json
import pickle
from datetime import datetime, UTC

base = Path(__file__).resolve().parents[1]
data = base / "data" / "processed" / "new_data"
outm = base / "models" / "severity"
outm.mkdir(parents=True, exist_ok=True)

def norm(x):
    x = np.asarray(x, dtype=float)
    mn, mx = x.min(), x.max()
    if mx == mn:
        return np.zeros_like(x)
    return (x - mn) / (mx - mn)

def run():
    dp = pd.read_csv(data / "clean_district_population.csv")
    dp = dp[dp["population"] > 0]

    districts = dp["district_code"].unique()
    records = []

    for d in districts:
        for t in range(5):
            records.append({
                "district_code": d,
                "time_step": t,
                "intensity": np.random.rand(),
                "reach": np.random.rand(),
                "escalation": np.random.rand(),
                "persistence": 1.0 if t > 1 else 0.0
            })

    df = pd.DataFrame(records)

    w = [0.4, 0.25, 0.2, 0.15]

    df["severity_score"] = (
        w[0] * norm(df["intensity"]) +
        w[1] * norm(df["reach"]) +
        w[2] * norm(df["escalation"]) +
        w[3] * norm(df["persistence"])
    )

    out = df[["district_code", "time_step", "severity_score"]]

    with open(outm / "severity_model.pkl", "wb") as f:
        pickle.dump(out, f)

    meta = {
        "district_universe": "population > 0",
        "weights": w,
        "time_steps": sorted(df["time_step"].unique().tolist()),
        "created_at": datetime.now(UTC).isoformat(),
        "schema_version": "v3.0"
    }

    with open(outm / "severity_metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    with open(outm / "severity_version.txt", "w") as f:
        f.write("severity_v3.0")

if __name__ == "__main__":
    run()
