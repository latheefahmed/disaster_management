import pandas as pd
from app.config import CORE_ENGINE_ROOT


def compute_unmet_risk():
    path = CORE_ENGINE_ROOT / "phase4" / "optimization" / "output" / "unmet_demand_u.csv"
    df = pd.read_csv(path)

    result = (
        df.groupby("district_code")["unmet_demand"]
        .sum()
        .reset_index()
        .to_dict(orient="records")
    )

    return result
