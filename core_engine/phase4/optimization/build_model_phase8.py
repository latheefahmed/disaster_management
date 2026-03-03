import os

import pulp
from pathlib import Path

from loaders import (
    load_demand,
    load_district_stock,
    load_state_stock,
    load_national_stock,
)
from model_sets import load_sets


def _lookup(df, key_cols, value_col):
    if df is None or df.empty:
        return {}
    out = {}
    for row in df[key_cols + [value_col]].itertuples(index=False, name=None):
        *keys, value = row
        normalized = []
        for key in keys:
            if isinstance(key, (int, float)):
                normalized.append(int(key) if float(key).is_integer() else float(key))
            else:
                normalized.append(str(key))
        out[tuple(normalized)] = float(value)
    return out


def build_model_phase8(
    demand_override_path=None,
    district_stock_override_path=None,
    state_stock_override_path=None,
    national_stock_override_path=None,
    current_time=None,
    horizon=1,
    w_unmet=1_000_000.0,
    w_hold=1.0,
    w_ship=2.0,
):
    base_path = Path(__file__).parents[2]
    early_time_bias = float(os.getenv("PHASE8_EARLY_TIME_BIAS", "0.10") or "0.10")
    early_time_bias = max(0.0, min(2.0, early_time_bias))

    demand_df = load_demand(
        base_path,
        demand_override_path=demand_override_path,
    )

    required_demand_cols = {"district_code", "resource_id", "time", "demand"}
    missing_demand_cols = required_demand_cols - set(demand_df.columns)
    if missing_demand_cols:
        raise ValueError(f"Demand data missing columns: {sorted(missing_demand_cols)}")

    demand_df["district_code"] = demand_df["district_code"].astype(str)
    demand_df["resource_id"] = demand_df["resource_id"].astype(str)
    demand_df["time"] = demand_df["time"].astype(int)

    all_times = sorted(int(t) for t in demand_df["time"].unique().tolist())
    if not all_times:
        raise ValueError("No time slots in demand")

    t0 = int(current_time) if current_time is not None else int(all_times[0])
    h = max(1, int(horizon))
    t_end = t0 + h - 1
    T = [int(t) for t in all_times if t0 <= int(t) <= t_end]
    if not T:
        raise ValueError(f"No demand rows in requested horizon window [{t0}, {t_end}]")

    demand_df = demand_df[demand_df["time"].isin(T)].copy()
    demand_df = demand_df.groupby(["district_code", "resource_id", "time"], as_index=False)["demand"].sum()
    demand_df = demand_df[demand_df["demand"].astype(float) > 0.0].copy()

    D_all, S_all, R_all, _L, _T_all, district_to_state = load_sets(base_path, demand_override_path=demand_override_path)
    D = sorted(set(str(d) for d in D_all).intersection(set(demand_df["district_code"].astype(str).unique().tolist())))
    R = sorted(set(str(r) for r in R_all).intersection(set(demand_df["resource_id"].astype(str).unique().tolist())))
    if not D or not R:
        raise ValueError("No active districts/resources for horizon window")

    district_stock = load_district_stock(
        base_path,
        district_stock_override_path=district_stock_override_path,
    )
    state_stock = load_state_stock(
        base_path,
        state_stock_override_path=state_stock_override_path,
    )
    national_stock = load_national_stock(
        base_path,
        national_stock_override_path=national_stock_override_path,
    )

    district_stock["district_code"] = district_stock["district_code"].astype(str)
    district_stock["resource_id"] = district_stock["resource_id"].astype(str)
    state_stock["state_code"] = state_stock["state_code"].astype(str)
    state_stock["resource_id"] = state_stock["resource_id"].astype(str)
    national_stock["resource_id"] = national_stock["resource_id"].astype(str)

    state_for_d = {str(d): str(district_to_state[str(d)]) for d in D if str(d) in district_to_state}
    D = [d for d in D if d in state_for_d]
    S = sorted({state_for_d[d] for d in D})

    demand_lookup = _lookup(demand_df, ["district_code", "resource_id", "time"], "demand")
    district_stock_lookup = _lookup(district_stock, ["district_code", "resource_id"], "quantity")
    state_stock_lookup = _lookup(state_stock, ["state_code", "resource_id"], "quantity")
    national_stock_lookup = _lookup(national_stock, ["resource_id"], "quantity")

    demand_slots = sorted(
        (str(d), str(r), int(t))
        for (d, r, t), q in demand_lookup.items()
        if float(q) > 0.0 and str(d) in state_for_d and str(d) in D and str(r) in R
    )
    demand_pairs = sorted({(d, r) for d, r, _ in demand_slots})
    demand_districts_by_resource: dict[str, set[str]] = {}
    for d, r, _ in demand_slots:
        demand_districts_by_resource.setdefault(str(r), set()).add(str(d))

    supply_districts_by_resource: dict[str, set[str]] = {}
    for (d, r), q in district_stock_lookup.items():
        if float(q or 0.0) > 0.0 and str(d) in D and str(r) in R:
            supply_districts_by_resource.setdefault(str(r), set()).add(str(d))

    state_has_stock = {(str(s), str(r)): float(q or 0.0) > 0.0 for (s, r), q in state_stock_lookup.items()}
    national_has_stock = {str(r): float(q or 0.0) > 0.0 for (r,), q in national_stock_lookup.items()}

    model = pulp.LpProblem("disaster_allocation_phase8", pulp.LpMinimize)

    inv_times = list(T) + [int(T[-1]) + 1]

    ship_index: list[tuple[str, str, str, int]] = []
    for r in R:
        demand_ds = demand_districts_by_resource.get(str(r), set())
        supply_ds = supply_districts_by_resource.get(str(r), set())
        if not demand_ds or not supply_ds:
            continue
        for t in T:
            for f in supply_ds:
                for to in demand_ds:
                    if f == to:
                        continue
                    ship_index.append((str(f), str(to), str(r), int(t)))

    inv_pairs: set[tuple[str, str]] = set(demand_pairs)
    for f, to, r, _ in ship_index:
        inv_pairs.add((str(f), str(r)))
        inv_pairs.add((str(to), str(r)))

    inv = {
        (d, r, t): pulp.LpVariable(f"inv_{d}_{r}_{t}", lowBound=0, cat="Continuous")
        for (d, r) in sorted(inv_pairs)
        for t in inv_times
    }

    ship = {
        (f, to, r, t): pulp.LpVariable(f"ship_{f}_{to}_{r}_{t}", lowBound=0, cat="Continuous")
        for (f, to, r, t) in ship_index
    }

    state_in = {
        (d, r, t): pulp.LpVariable(f"sin_{state_for_d[d]}_{d}_{r}_{t}", lowBound=0, cat="Continuous")
        for (d, r, t) in demand_slots
        if bool(state_has_stock.get((state_for_d[str(d)], str(r)), False))
    }

    nat_in = {
        (d, r, t): pulp.LpVariable(f"nin_{d}_{r}_{t}", lowBound=0, cat="Continuous")
        for (d, r, t) in demand_slots
        if bool(national_has_stock.get(str(r), False))
    }

    alloc = {
        (d, r, t): pulp.LpVariable(f"alloc_{d}_{r}_{t}", lowBound=0, cat="Continuous")
        for (d, r, t) in demand_slots
    }

    alloc_district = {
        (d, r, t): pulp.LpVariable(f"allocd_{d}_{r}_{t}", lowBound=0, cat="Continuous")
        for (d, r, t) in demand_slots
    }

    alloc_state = {
        (d, r, t): pulp.LpVariable(f"allocs_{d}_{r}_{t}", lowBound=0, cat="Continuous")
        for (d, r, t) in demand_slots
        if (d, r, t) in state_in
    }

    alloc_national = {
        (d, r, t): pulp.LpVariable(f"allocn_{d}_{r}_{t}", lowBound=0, cat="Continuous")
        for (d, r, t) in demand_slots
        if (d, r, t) in nat_in
    }

    unmet = {
        (d, r, t): pulp.LpVariable(f"unmet_{d}_{r}_{t}", lowBound=0, cat="Continuous")
        for (d, r, t) in demand_slots
    }

    for d, r in sorted(inv_pairs):
            init_q = float(district_stock_lookup.get((str(d), str(r)), 0.0))
            model += (inv[(d, r, int(T[0]))] == init_q, f"init_inventory_{d}_{r}")

    for d, r, t in demand_slots:
                dem = float(demand_lookup.get((str(d), str(r), int(t)), 0.0))
                model += (alloc[(d, r, t)] + unmet[(d, r, t)] == dem, f"demand_sat_{d}_{r}_{t}")
                model += (
                    alloc_district[(d, r, t)]
                    + alloc_state.get((d, r, t), 0.0)
                    + alloc_national.get((d, r, t), 0.0)
                    == alloc[(d, r, t)],
                    f"alloc_source_split_{d}_{r}_{t}",
                )
                if (d, r, t) in alloc_state and (d, r, t) in state_in:
                    model += (alloc_state[(d, r, t)] <= state_in[(d, r, t)], f"alloc_state_cap_{d}_{r}_{t}")
                if (d, r, t) in alloc_national and (d, r, t) in nat_in:
                    model += (alloc_national[(d, r, t)] <= nat_in[(d, r, t)], f"alloc_national_cap_{d}_{r}_{t}")

    for d, r in sorted(inv_pairs):
            for t in T:
                outbound = pulp.lpSum(ship[(d, to, r, t)] for to in D if to != d and (d, to, r, t) in ship)
                inbound = pulp.lpSum(ship[(f, d, r, t)] for f in D if f != d and (f, d, r, t) in ship)
                model += (outbound <= inv[(d, r, t)], f"shipment_out_cap_{d}_{r}_{t}")
                if (d, r, t) in alloc_district:
                    model += (
                        alloc_district[(d, r, t)] <= inv[(d, r, t)] + inbound - outbound,
                        f"alloc_district_cap_{d}_{r}_{t}",
                    )
                model += (
                    inv[(d, r, t + 1)]
                    == inv[(d, r, t)]
                    + inbound
                    + state_in.get((d, r, t), 0.0)
                    + nat_in.get((d, r, t), 0.0)
                    - outbound
                    - alloc.get((d, r, t), 0.0),
                    f"inventory_balance_{d}_{r}_{t}",
                )

    for s in S:
        ds = [d for d in D if state_for_d[d] == s]
        for r in R:
            cap = float(state_stock_lookup.get((str(s), str(r)), 0.0))
            model += (
                pulp.lpSum(state_in[(d, r, t)] for d in ds for t in T if (d, r, t) in state_in) <= cap,
                f"state_stock_total_{s}_{r}",
            )

    for r in R:
        cap = float(national_stock_lookup.get((str(r),), 0.0))
        model += (
            pulp.lpSum(nat_in[(d, r, t)] for d in D for t in T if (d, r, t) in nat_in) <= cap,
            f"national_stock_total_{r}",
        )

    t_min = int(min(T))
    t_span = max(1, int(max(T) - t_min))

    def _time_unmet_weight(t: int) -> float:
        rank = (int(t) - t_min) / float(t_span)
        return 1.0 + (early_time_bias * max(0.0, 1.0 - rank))

    model += (
        pulp.lpSum(float(w_unmet) * _time_unmet_weight(t) * var for (d, r, t), var in unmet.items())
        + pulp.lpSum(float(w_hold) * var for (d, r, t), var in inv.items() if int(t) in T)
        + pulp.lpSum(
            float(w_ship) * var
            for (_, _, _, _), var in ship.items()
        )
    )

    print("MODEL_BUILD_SUMMARY", {
        "window_start": int(T[0]),
        "window_end": int(T[-1]),
        "DEMAND_ROWS": int(len(demand_df.index)),
        "DEMAND_SLOTS": int(len(demand_slots)),
        "INV_PAIRS": int(len(inv_pairs)),
        "SHIP_ARCS": int(len(ship_index)),
    })
    print("VARIABLE_COUNT", len(model.variables()))
    print("CONSTRAINT_COUNT", len(model.constraints))
    print("DEMAND_ROWS", len(demand_df))

    metadata = {
        "districts": D,
        "states": S,
        "resources": R,
        "times": T,
        "state_for_district": state_for_d,
        "window_start": int(T[0]),
        "window_end": int(T[-1]),
    }

    variables = {
        "inventory": inv,
        "shipments": ship,
        "state_in": state_in,
        "national_in": nat_in,
        "allocation": alloc,
        "allocation_district": alloc_district,
        "allocation_state": alloc_state,
        "allocation_national": alloc_national,
        "unmet": unmet,
    }

    return model, metadata, variables
