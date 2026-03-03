from app.engine_bridge.csv_loader import (
    load_allocation_csv,
    load_unmet_csv,
    load_inventory_csv,
    load_shipment_plan_csv,
)


REQUIRED_ALLOC_COLUMNS = {
    "supply_level",
    "resource_id",
    "district_code",
    "state_code",
    "time",
    "allocated_quantity"
}

REQUIRED_UNMET_COLUMNS = {
    "resource_id",
    "district_code",
    "time",
    "unmet_quantity"
}

REQUIRED_INVENTORY_COLUMNS = {
    "district_code",
    "resource_id",
    "time",
    "quantity",
}

REQUIRED_SHIPMENT_COLUMNS = {
    "from_district",
    "to_district",
    "resource_id",
    "time",
    "quantity",
    "status",
}


def parse_allocations():
    df = load_allocation_csv()

    if not REQUIRED_ALLOC_COLUMNS.issubset(df.columns):
        raise ValueError(
            f"allocation_x.csv missing columns: {REQUIRED_ALLOC_COLUMNS - set(df.columns)}"
        )

    if len(df.index) == 0:
        return []

    return df.to_dict(orient="records")


def parse_unmet():
    df = load_unmet_csv()

    if not REQUIRED_UNMET_COLUMNS.issubset(df.columns):
        raise ValueError(
            f"unmet_demand_u.csv missing columns: {REQUIRED_UNMET_COLUMNS - set(df.columns)}"
        )

    if len(df.index) == 0:
        return []

    return df.to_dict(orient="records")


def parse_inventory_snapshots():
    df = load_inventory_csv()

    if len(df.index) == 0:
        return []

    if not REQUIRED_INVENTORY_COLUMNS.issubset(df.columns):
        raise ValueError(
            f"inventory_t.csv missing columns: {REQUIRED_INVENTORY_COLUMNS - set(df.columns)}"
        )

    return df.to_dict(orient="records")


def parse_shipment_plan():
    df = load_shipment_plan_csv()

    if len(df.index) == 0:
        return []

    if not REQUIRED_SHIPMENT_COLUMNS.issubset(df.columns):
        raise ValueError(
            f"shipment_plan.csv missing columns: {REQUIRED_SHIPMENT_COLUMNS - set(df.columns)}"
        )

    return df.to_dict(orient="records")
