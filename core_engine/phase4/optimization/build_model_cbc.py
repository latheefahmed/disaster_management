import pulp
from pathlib import Path

from loaders import (
    load_demand,
    load_district_stock,
    load_state_stock,
    load_national_stock,
)

from model_sets import load_sets

from model_constraints import (
    add_demand_constraints,
    add_district_stock_constraints,
    add_state_stock_constraints,
    add_national_stock_constraints,
    add_flow_validity_constraints,
)

from model_objective import add_objective
from model_variables import build_flow_variables


DISTRICT = "district"
STATE = "state"
NATIONAL = "national"

# Objective feature hooks (priority / urgency) for governance checks.
PRIORITY_WEIGHT = 1.0
URGENCY_WEIGHT = 1.0


def build_model_cbc(
    demand_override_path=None,
    district_stock_override_path=None,
    state_stock_override_path=None,
    national_stock_override_path=None,
    horizon: int = 30,
):

    print("=== LOADED BUILD_MODEL_CBC VERSION 1000 ===")

    base_path = Path(__file__).parents[2]

    # --------------------------------------------------------
    # 1. LOAD DEMAND
    # --------------------------------------------------------

    demand_df = load_demand(
        base_path,
        demand_override_path=demand_override_path
    )

    required_demand_cols = {"district_code", "resource_id", "time", "demand"}
    missing_demand_cols = required_demand_cols - set(demand_df.columns)
    if missing_demand_cols:
        raise ValueError(f"Demand data missing columns: {sorted(missing_demand_cols)}")

    demand_df["district_code"] = demand_df["district_code"].astype(str)
    demand_df["resource_id"] = demand_df["resource_id"].astype(str)
    demand_df["time"] = demand_df["time"].astype(int)

    configured_horizon = max(1, int(horizon))
    max_time = int(demand_df["time"].max()) if not demand_df.empty else 0
    effective_horizon = min(configured_horizon, max_time + 1)
    max_included_time = int(effective_horizon - 1)

    demand_df = demand_df[(demand_df["time"] >= 0) & (demand_df["time"] <= max_included_time)].copy()

    ACTIVE_DISTRICTS = sorted(
        demand_df["district_code"].unique().tolist()
    )
    ACTIVE_RESOURCES = sorted(
        demand_df["resource_id"].unique().tolist()
    )

    # --------------------------------------------------------
    # 2. LOAD GLOBAL SETS
    # --------------------------------------------------------

    D, S, R, L, T, district_to_state = load_sets(base_path)

    T = list(range(effective_horizon))

    D = sorted(set(D).intersection(ACTIVE_DISTRICTS))
    R = sorted(set(R).intersection(ACTIVE_RESOURCES))
    S = sorted({district_to_state[d] for d in D if d in district_to_state})

    print("Solver District Set:", sorted(D))
    print("Count:", len(D))

    # --------------------------------------------------------
    # 3. LOAD STOCKS
    # --------------------------------------------------------

    district_stock = load_district_stock(
        base_path,
        district_stock_override_path=district_stock_override_path,
    )

    state_stock = load_state_stock(
        base_path,
        state_stock_override_path=state_stock_override_path
    )

    national_stock = load_national_stock(
        base_path,
        national_stock_override_path=national_stock_override_path
    )

    for frame_name, frame, req in [
        ("district_stock", district_stock, {"district_code", "resource_id", "quantity"}),
        ("state_stock", state_stock, {"state_code", "resource_id", "quantity"}),
        ("national_stock", national_stock, {"resource_id", "quantity"}),
    ]:
        missing = req - set(frame.columns)
        if missing:
            raise ValueError(f"{frame_name} missing columns: {sorted(missing)}")

    total_demand = float(demand_df["demand"].sum()) if not demand_df.empty else 0.0
    total_district_stock = float(district_stock["quantity"].sum()) if not district_stock.empty else 0.0
    total_state_stock = float(state_stock["quantity"].sum()) if not state_stock.empty else 0.0
    total_national_stock = float(national_stock["quantity"].sum()) if not national_stock.empty else 0.0

    print("=== RUN INPUT SUMMARY ===")
    print(f"districts={len(D)} resources={len(R)} time_steps={len(T)}")
    print(f"total_demand={total_demand}")
    print(f"total_district_stock={total_district_stock}")
    print(f"total_state_stock={total_state_stock}")
    print(f"total_national_stock={total_national_stock}")
    print("=========================")

    if total_demand <= 0:
        raise ValueError("Total demand is zero; aborting run to prevent silent objective=0 solve")

    # --------------------------------------------------------
    # 4. CREATE MODEL
    # --------------------------------------------------------

    model = pulp.LpProblem("disaster_allocation", pulp.LpMinimize)

    # --------------------------------------------------------
    # 5. VARIABLES
    # --------------------------------------------------------

    x, u = build_flow_variables(
        model=model,
        districts=D,
        states=S,
        resources=R,
        levels=L,
        times=T,
        district_to_state=district_to_state
    )

    # --------------------------------------------------------
    # 6. DEMAND CONSTRAINTS
    # --------------------------------------------------------

    add_demand_constraints(
        model, demand_df, x, u, D, S, R, L, T
    )

    # --------------------------------------------------------
    # 7. STOCK CONSTRAINTS
    # --------------------------------------------------------

    add_district_stock_constraints(
        model, district_stock, x, D, R, S, T
    )

    add_state_stock_constraints(
        model, state_stock, x, D, R, S, T, district_to_state
    )

    add_national_stock_constraints(
        model, national_stock, x, D, R, S, T
    )

    add_flow_validity_constraints(
        model, x, D, R, S, T, district_to_state
    )

    # --------------------------------------------------------
    # 8. OBJECTIVE
    # --------------------------------------------------------

    add_objective(model, x, u)

    print("MODEL_BUILD_SUMMARY", {
        "configured_horizon": int(configured_horizon),
        "max_time": int(max_time),
        "effective_horizon": int(effective_horizon),
        "districts": len(D),
        "resources": len(R),
        "times": len(T),
    })
    print("VARIABLE_COUNT", len(model.variables()))
    print("CONSTRAINT_COUNT", len(model.constraints))
    print("DEMAND_ROWS", len(demand_df))

    return model
