from pathlib import Path
import pandas as pd
import numpy as np
import pickle

base = Path(__file__).resolve().parents[1]
data = base / "data" / "processed" / "new_data"
outm = base / "models"

def norm(x):
    x = x.astype(float)
    mn, mx = x.min(), x.max()
    if mx == mn:
        return np.zeros_like(x)
    return (x - mn) / (mx - mn)

def run():
    dp = pd.read_csv(data / "clean_district_population.csv")
    dp = dp[dp["population"] > 0]

    out = pd.DataFrame({
        "district_code": dp["district_code"],
        "exposure_score": norm(dp["population"]),
        "capacity_score": norm(dp["households"])
    })

    with open(outm / "exposure_capacity.pkl", "wb") as f:
        pickle.dump(out, f)

if __name__ == "__main__":
    run()
