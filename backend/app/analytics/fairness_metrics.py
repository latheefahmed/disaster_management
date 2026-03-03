import pandas as pd
from app.config import CORE_ENGINE_ROOT


def compute_fairness():
    path = CORE_ENGINE_ROOT / "phase4" / "optimization" / "output" / "allocation_x.csv"
    df = pd.read_csv(path)

    result = (
        df.groupby("district_code")["allocated_quantity"]
        .sum()
        .reset_index()
        .to_dict(orient="records")
    )

    return result
