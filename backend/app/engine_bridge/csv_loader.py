import pandas as pd
from app.config import CORE_ENGINE_ROOT


def load_allocation_csv():
    path = (
        CORE_ENGINE_ROOT
        / "phase4"
        / "optimization"
        / "output"
        / "allocation_x.csv"
    )
    return pd.read_csv(path)


def load_unmet_csv():
    path = (
        CORE_ENGINE_ROOT
        / "phase4"
        / "optimization"
        / "output"
        / "unmet_demand_u.csv"
    )

    if not path.exists():
        path = (
            CORE_ENGINE_ROOT
            / "phase4"
            / "optimization"
            / "output"
            / "unmet_u.csv"
        )

    return pd.read_csv(path)


def load_inventory_csv():
    path = (
        CORE_ENGINE_ROOT
        / "phase4"
        / "optimization"
        / "output"
        / "inventory_t.csv"
    )
    if not path.exists():
        return pd.DataFrame(columns=["district_code", "resource_id", "time", "quantity"])
    return pd.read_csv(path)


def load_shipment_plan_csv():
    path = (
        CORE_ENGINE_ROOT
        / "phase4"
        / "optimization"
        / "output"
        / "shipment_plan.csv"
    )
    if not path.exists():
        return pd.DataFrame(columns=["from_district", "to_district", "resource_id", "time", "quantity", "status"])
    return pd.read_csv(path)
