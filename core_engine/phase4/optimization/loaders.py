import pandas as pd
import os
from pilot_config import PILOT_STATE_CODE, MAX_DISTRICTS, PILOT_RESOURCES

# =================================================
# GLOBAL DEMAND SCALING
# =================================================

DEMAND_UNIT_MULTIPLIER = 1

# -------------------------------------------------
# Helpers
# -------------------------------------------------

def _resolve_root(arg):
    if arg is None:
        return "."
    return arg


def _try_paths(root, rel):
    return [
        os.path.join(root, rel),
        os.path.join(root, "core_engine", rel)
    ]


def _read_csv(root, rel):
    for p in _try_paths(root, rel):
        if os.path.exists(p):
            return pd.read_csv(p)
    raise FileNotFoundError(rel)


def _resolve_override(root, path):
    if path is None:
        return None
    if os.path.isabs(path):
        return path
    return os.path.join(root, path)

# -------------------------------------------------
# Geography
# -------------------------------------------------

def load_state_codes(arg=None):
    root = _resolve_root(arg)
    df = _read_csv(root, "data/processed/new_data/clean_state_codes.csv")

    if PILOT_STATE_CODE is not None:
        df = df[df["state_code"].astype(str) == str(PILOT_STATE_CODE)]

    df["state_code"] = df["state_code"].astype(str)
    return df


def load_district_codes(arg=None):
    root = _resolve_root(arg)
    df = _read_csv(root, "data/processed/new_data/clean_district_codes.csv")

    if PILOT_STATE_CODE is not None:
        df = df[df["state_code"].astype(str) == str(PILOT_STATE_CODE)]

    if MAX_DISTRICTS is not None:
        df = df.sort_values("district_code").head(MAX_DISTRICTS)

    df["district_code"] = df["district_code"].astype(str)
    df["state_code"] = df["state_code"].astype(str)
    return df

# -------------------------------------------------
# Resources
# -------------------------------------------------

def load_resource_catalog(arg=None):
    root = _resolve_root(arg)
    df = _read_csv(root, "phase4/resources/schema/resource_catalog.csv")

    if PILOT_RESOURCES is not None:
        df = df[df["resource_id"].isin(PILOT_RESOURCES)]

    df["resource_id"] = df["resource_id"].astype(str)
    return df

# -------------------------------------------------
# Stock
# -------------------------------------------------

def load_district_stock(arg=None, district_stock_override_path=None):
    root = _resolve_root(arg)

    if district_stock_override_path:
        path = _resolve_override(root, district_stock_override_path)
        df = pd.read_csv(path)
    else:
        df = _read_csv(root, "phase4/resources/synthetic_data/district_resource_stock.csv")

    if PILOT_RESOURCES is not None:
        df = df[df["resource_id"].isin(PILOT_RESOURCES)]

    df["district_code"] = df["district_code"].astype(str)
    df["resource_id"] = df["resource_id"].astype(str)

    return df.groupby(
        ["district_code", "resource_id"],
        as_index=False
    )["quantity"].sum()


def load_state_stock(arg=None, state_stock_override_path=None):
    root = _resolve_root(arg)

    if state_stock_override_path:
        path = _resolve_override(root, state_stock_override_path)
        df = pd.read_csv(path)
    else:
        df = _read_csv(root, "phase4/resources/synthetic_data/state_resource_stock.csv")

    if PILOT_STATE_CODE is not None:
        df = df[df["state_code"].astype(str) == str(PILOT_STATE_CODE)]

    if PILOT_RESOURCES is not None:
        df = df[df["resource_id"].isin(PILOT_RESOURCES)]

    df["state_code"] = df["state_code"].astype(str)
    df["resource_id"] = df["resource_id"].astype(str)

    return df.groupby(
        ["state_code", "resource_id"],
        as_index=False
    )["quantity"].sum()


def load_national_stock(arg=None, national_stock_override_path=None):
    root = _resolve_root(arg)

    if national_stock_override_path:
        path = _resolve_override(root, national_stock_override_path)
        df = pd.read_csv(path)
    else:
        df = _read_csv(root, "phase4/resources/synthetic_data/national_resource_stock.csv")

    if PILOT_RESOURCES is not None:
        df = df[df["resource_id"].isin(PILOT_RESOURCES)]

    df["resource_id"] = df["resource_id"].astype(str)

    return df.groupby(
        ["resource_id"],
        as_index=False
    )["quantity"].sum()

# -------------------------------------------------
# Demand
# -------------------------------------------------

def load_demand(arg=None, demand_override_path=None):
    root = _resolve_root(arg)

    if demand_override_path:
        path = _resolve_override(root, demand_override_path)
        df = pd.read_csv(path)
    else:
        df = _read_csv(root, "phase3/output/district_resource_demand.csv")

    if PILOT_RESOURCES is not None:
        df = df[df["resource_id"].isin(PILOT_RESOURCES)]

    required = {"district_code", "resource_id", "time", "demand"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Demand CSV missing required columns: {sorted(missing)}")

    if "demand_mode" in df.columns and "source" in df.columns:
        mode = df["demand_mode"].astype(str).str.lower()
        src = df["source"].astype(str).str.lower()

        keep_human_only = (mode == "human_only") & (src == "human")
        keep_baseline_only = (mode == "baseline_only") & (src == "baseline")
        keep_mixed = mode == "baseline_plus_human"

        df = df[keep_human_only | keep_baseline_only | keep_mixed]

    df["district_code"] = df["district_code"].astype(str)
    df["resource_id"] = df["resource_id"].astype(str)
    df["time"] = df["time"].astype(int)

    df["demand"] = df["demand"] * DEMAND_UNIT_MULTIPLIER

    return df.groupby(
        ["resource_id", "district_code", "time"],
        as_index=False
    )["demand"].sum()
