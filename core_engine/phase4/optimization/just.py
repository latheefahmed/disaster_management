import os
import pandas as pd

from loaders import (
    load_demand,
    load_district_stock,
    load_state_stock,
    load_national_stock,
)

BASE = "core_engine"

ALLOC_PATH = os.path.join(
    BASE, "phase4/optimization/output/allocation_x.csv"
)

UNMET_PATH = os.path.join(
    BASE, "phase4/optimization/output/unmet_demand_u.csv"
)

DEMAND_PATH = os.path.join(
    BASE, "phase3/output/district_resource_demand.csv"
)

TOL = 1e-2


def safe_read_csv(path):
    if not os.path.exists(path):
        print("Missing:", path)
        return pd.DataFrame()

    if os.path.getsize(path) == 0:
        print("Empty file:", path)
        return pd.DataFrame()

    return pd.read_csv(path)


def main():

    alloc = safe_read_csv(ALLOC_PATH)
    unmet = safe_read_csv(UNMET_PATH)
    demand_raw = safe_read_csv(DEMAND_PATH)

    demand = load_demand(BASE)
    district_stock = load_district_stock(BASE)
    state_stock = load_state_stock(BASE)
    national_stock = load_national_stock(BASE)

    print("\nRow counts:")
    print(" allocations:", len(alloc))
    print(" unmet:", len(unmet))
    print(" demand_raw (phase3):", len(demand_raw))
    print(" demand_scaled (loader):", len(demand))

    if len(alloc) == 0 and len(unmet) == 0:
        print("\nNo solver output rows to test.")
        return

    if len(alloc) > 0:
        alloc["resource_id"] = alloc["resource_id"].astype(str)
        alloc["district_code"] = alloc["district_code"].astype(str)
        alloc["state_code"] = alloc["state_code"].astype(str)
        alloc["time"] = alloc["time"].astype(int)
        alloc["allocated_quantity"] = alloc["allocated_quantity"].astype(float)
    else:
        alloc = pd.DataFrame(
            columns=[
                "supply_level",
                "resource_id",
                "state_code",
                "district_code",
                "time",
                "allocated_quantity",
            ]
        )

    if len(unmet) > 0:
        unmet["resource_id"] = unmet["resource_id"].astype(str)
        unmet["district_code"] = unmet["district_code"].astype(str)
        unmet["time"] = unmet["time"].astype(int)
        unmet["unmet_quantity"] = unmet["unmet_quantity"].astype(float)
    else:
        unmet = pd.DataFrame(
            columns=["resource_id", "district_code", "time", "unmet_quantity"]
        )

    demand["resource_id"] = demand["resource_id"].astype(str)
    demand["district_code"] = demand["district_code"].astype(str)
    demand["time"] = demand["time"].astype(int)
    demand["demand"] = demand["demand"].astype(float)

    alloc_mass = alloc.groupby(
        ["resource_id", "district_code", "time"],
        as_index=False
    )["allocated_quantity"].sum()

    unmet_mass = unmet.groupby(
        ["resource_id", "district_code", "time"],
        as_index=False
    )["unmet_quantity"].sum()

    mass_df = demand.merge(
        alloc_mass,
        on=["resource_id", "district_code", "time"],
        how="left"
    ).merge(
        unmet_mass,
        on=["resource_id", "district_code", "time"],
        how="left"
    )

    mass_df["allocated_quantity"] = mass_df["allocated_quantity"].fillna(0.0)
    mass_df["unmet_quantity"] = mass_df["unmet_quantity"].fillna(0.0)
    mass_df["gap"] = (
        mass_df["allocated_quantity"]
        + mass_df["unmet_quantity"]
        - mass_df["demand"]
    )

    bad_mass = mass_df[mass_df["gap"].abs() > TOL]

    print("\nMass balance (all demand rows):")
    print(" rows checked:", len(mass_df))
    print(" max abs gap:", float(mass_df["gap"].abs().max()))
    print(" rows outside tol:", len(bad_mass))

    district_stock["district_code"] = district_stock["district_code"].astype(str)
    district_stock["resource_id"] = district_stock["resource_id"].astype(str)
    state_stock["state_code"] = state_stock["state_code"].astype(str)
    state_stock["resource_id"] = state_stock["resource_id"].astype(str)
    national_stock["resource_id"] = national_stock["resource_id"].astype(str)

    district_used = alloc[alloc["supply_level"] == "district"].groupby(
        ["district_code", "resource_id", "time"],
        as_index=False
    )["allocated_quantity"].sum()

    district_cap = district_stock.rename(columns={"quantity": "cap"})
    district_check = district_used.merge(
        district_cap,
        on=["district_code", "resource_id"],
        how="left"
    )
    district_check["cap"] = district_check["cap"].fillna(0.0)
    district_check["over"] = district_check["allocated_quantity"] - district_check["cap"]
    district_viol = district_check[district_check["over"] > TOL]

    state_used = alloc[alloc["supply_level"] == "state"].groupby(
        ["state_code", "resource_id", "time"],
        as_index=False
    )["allocated_quantity"].sum()

    state_cap = state_stock.rename(columns={"quantity": "cap"})
    state_check = state_used.merge(
        state_cap,
        on=["state_code", "resource_id"],
        how="left"
    )
    state_check["cap"] = state_check["cap"].fillna(0.0)
    state_check["over"] = state_check["allocated_quantity"] - state_check["cap"]
    state_viol = state_check[state_check["over"] > TOL]

    national_used = alloc[alloc["supply_level"] == "national"].groupby(
        ["resource_id", "time"],
        as_index=False
    )["allocated_quantity"].sum()

    national_cap = national_stock.rename(columns={"quantity": "cap"})
    national_check = national_used.merge(
        national_cap,
        on=["resource_id"],
        how="left"
    )
    national_check["cap"] = national_check["cap"].fillna(0.0)
    national_check["over"] = national_check["allocated_quantity"] - national_check["cap"]
    national_viol = national_check[national_check["over"] > TOL]

    print("\nStock feasibility checks:")
    print(" district violations:", len(district_viol))
    print(" state violations:", len(state_viol))
    print(" national violations:", len(national_viol))

    total_demand = float(demand["demand"].sum())
    total_unmet = float(unmet["unmet_quantity"].sum()) if len(unmet) > 0 else 0.0
    total_alloc = float(alloc["allocated_quantity"].sum()) if len(alloc) > 0 else 0.0
    served = max(0.0, total_demand - total_unmet)
    service_level = (served / total_demand) if total_demand > 0 else 0.0

    level_cost = {
        "district": 1.0,
        "state": 2.0,
        "national": 3.0,
    }
    flow_cost = 0.0
    if len(alloc) > 0:
        flow_cost = float(
            alloc.apply(
                lambda r: level_cost.get(str(r["supply_level"]), 1.0) * float(r["allocated_quantity"]),
                axis=1
            ).sum()
        )

    unmet_penalty = 1_000_000.0
    objective_est = unmet_penalty * total_unmet + flow_cost

    print("\nScenario quality summary:")
    print(" total demand:", total_demand)
    print(" total allocated:", total_alloc)
    print(" total unmet:", total_unmet)
    print(" service level (%):", round(100.0 * service_level, 4))
    print(" estimated objective:", objective_est)

    if len(bad_mass) == 0 and len(district_viol) == 0 and len(state_viol) == 0 and len(national_viol) == 0:
        print("\nPASS: Full scenario output is feasible and consistent")
    else:
        print("\nFAIL: Scenario output has consistency/feasibility issues")


if __name__ == "__main__":
    main()
