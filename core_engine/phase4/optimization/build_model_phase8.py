import os
from pathlib import Path

import pandas as pd
import pulp

from loaders import (
    load_demand,
    load_district_stock,
    load_national_stock,
    load_state_stock,
)
from model_sets import load_sets


def _lookup(df, key_cols, value_col):
    if df is None or df.empty or value_col not in df.columns:
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


def _load_state_adjacency(base_path: Path, states: list[str]) -> dict[str, set[str]]:
    """Load optional adjacency; fallback to deterministic code-neighborhood graph."""
    state_set = {str(s) for s in states}
    adjacency: dict[str, set[str]] = {str(s): set() for s in states}

    explicit_path = os.getenv("STATE_ADJACENCY_CSV", "").strip()
    candidate_paths = []
    if explicit_path:
        candidate_paths.append(Path(explicit_path))
    candidate_paths.append(base_path / "phase4" / "resources" / "synthetic_data" / "state_adjacency.csv")

    for path in candidate_paths:
        try:
            if not path.exists():
                continue
            adj_df = pd.read_csv(path)
            if not {"state_code", "neighbor_state_code"}.issubset(adj_df.columns):
                continue
            for row in adj_df[["state_code", "neighbor_state_code"]].itertuples(index=False):
                a = str(row.state_code)
                b = str(row.neighbor_state_code)
                if a in state_set and b in state_set and a != b:
                    adjacency[a].add(b)
                    adjacency[b].add(a)
            return adjacency
        except Exception:
            continue

    ordered = sorted(list(state_set), key=lambda x: (len(str(x)), str(x)))
    if len(ordered) <= 1:
        return adjacency

    # Without an explicit map, use a complete inter-state fallback graph so
    # cross-state escalation is feasible for any discovered state pair.
    for s in ordered:
        adjacency[s].update({o for o in ordered if o != s})

    return adjacency


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

    neighbor_stock_utilization_cap = float(os.getenv("NEIGHBOR_STOCK_UTILIZATION_CAP", "0.20") or "0.20")
    neighbor_stock_utilization_cap = max(0.05, min(1.0, neighbor_stock_utilization_cap))

    demand_df = load_demand(base_path, demand_override_path=demand_override_path)
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
    signal_cols = [c for c in ["priority", "urgency", "time_index"] if c in demand_df.columns]
    demand_df = demand_df.groupby(["district_code", "resource_id", "time"], as_index=False)[["demand"] + signal_cols].sum()
    demand_df = demand_df[demand_df["demand"].astype(float) > 0.0].copy()

    D_all, _S_all, R_all, _L, _T_all, district_to_state = load_sets(base_path, demand_override_path=demand_override_path)

    D = sorted(set(str(d) for d in D_all).intersection(set(demand_df["district_code"].astype(str).unique().tolist())))
    R = sorted(set(str(r) for r in R_all).intersection(set(demand_df["resource_id"].astype(str).unique().tolist())))
    if not D or not R:
        raise ValueError("No active districts/resources for horizon window")

    district_stock = load_district_stock(base_path, district_stock_override_path=district_stock_override_path)
    state_stock = load_state_stock(base_path, state_stock_override_path=state_stock_override_path)
    national_stock = load_national_stock(base_path, national_stock_override_path=national_stock_override_path)

    district_stock["district_code"] = district_stock["district_code"].astype(str)
    district_stock["resource_id"] = district_stock["resource_id"].astype(str)
    state_stock["state_code"] = state_stock["state_code"].astype(str)
    state_stock["resource_id"] = state_stock["resource_id"].astype(str)
    national_stock["resource_id"] = national_stock["resource_id"].astype(str)

    state_for_d = {str(d): str(district_to_state[str(d)]) for d in D if str(d) in district_to_state}
    D = [d for d in D if d in state_for_d]
    demand_states = {state_for_d[d] for d in D}

    stock_origin_states = {
        str(row.state_code)
        for row in state_stock.itertuples(index=False)
        if str(row.resource_id) in set(R) and float(row.quantity or 0.0) > 0.0
    }

    # Keep demand-bearing states and add stock-bearing origin states so neighbor
    # flows can exist even when no district in that state has direct demand.
    S = sorted(set(demand_states).union(stock_origin_states))
    adjacency = _load_state_adjacency(base_path, S)

    demand_lookup = _lookup(demand_df, ["district_code", "resource_id", "time"], "demand")
    priority_lookup = _lookup(demand_df, ["district_code", "resource_id", "time"], "priority")
    urgency_lookup = _lookup(demand_df, ["district_code", "resource_id", "time"], "urgency")
    time_index_lookup = _lookup(demand_df, ["district_code", "resource_id", "time"], "time_index")

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

    state_in = {}
    for (d, r, t) in demand_slots:
        target_state = str(state_for_d[str(d)])
        origins = {target_state}
        origins.update({str(o) for o in adjacency.get(target_state, set())})
        for origin_state in sorted(origins):
            if not bool(state_has_stock.get((str(origin_state), str(r)), False)):
                continue
            state_in[(str(origin_state), str(d), str(r), int(t))] = pulp.LpVariable(
                f"sin_{origin_state}_{d}_{r}_{t}",
                lowBound=0,
                cat="Continuous",
            )

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

    alloc_state_by_origin = {
        (origin_state, d, r, t): pulp.LpVariable(f"allocs_{origin_state}_{d}_{r}_{t}", lowBound=0, cat="Continuous")
        for (origin_state, d, r, t) in state_in.keys()
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
        demand_q = float(demand_lookup.get((str(d), str(r), int(t)), 0.0))

        state_alloc_sum = pulp.lpSum(
            alloc_state_by_origin[(origin_state, d, r, t)]
            for origin_state in S
            if (origin_state, d, r, t) in alloc_state_by_origin
        )
        national_alloc_var = alloc_national.get((d, r, t), 0.0)

        model += (
            alloc[(d, r, t)] == alloc_district[(d, r, t)] + state_alloc_sum + national_alloc_var,
            f"alloc_split_{d}_{r}_{t}",
        )
        model += (
            alloc[(d, r, t)] + unmet[(d, r, t)] == demand_q,
            f"demand_balance_{d}_{r}_{t}",
        )
        model += (
            alloc_district[(d, r, t)] <= inv[(d, r, t)],
            f"alloc_district_cap_{d}_{r}_{t}",
        )

        for origin_state in S:
            if (origin_state, d, r, t) in alloc_state_by_origin and (origin_state, d, r, t) in state_in:
                model += (
                    alloc_state_by_origin[(origin_state, d, r, t)] <= state_in[(origin_state, d, r, t)],
                    f"alloc_state_cap_{origin_state}_{d}_{r}_{t}",
                )

        if (d, r, t) in alloc_national and (d, r, t) in nat_in:
            model += (
                alloc_national[(d, r, t)] <= nat_in[(d, r, t)],
                f"alloc_national_cap_{d}_{r}_{t}",
            )

    for d, r in sorted(inv_pairs):
        for t in T:
            outbound = pulp.lpSum(ship[(d, to, r, t)] for to in D if to != d and (d, to, r, t) in ship)
            inbound = pulp.lpSum(ship[(f, d, r, t)] for f in D if f != d and (f, d, r, t) in ship)
            state_inbound = pulp.lpSum(
                state_in[(origin_state, d, r, t)]
                for origin_state in S
                if (origin_state, d, r, t) in state_in
            )
            national_inbound = nat_in.get((d, r, t), 0.0)
            local_alloc = alloc.get((d, r, t), 0.0)

            model += (outbound <= inv[(d, r, t)], f"shipment_out_cap_{d}_{r}_{t}")
            model += (
                inv[(d, r, t + 1)]
                == inv[(d, r, t)]
                + inbound
                + state_inbound
                + national_inbound
                - outbound
                - local_alloc,
                f"inventory_balance_{d}_{r}_{t}",
            )

    for s in S:
        for r in R:
            cap = float(state_stock_lookup.get((str(s), str(r)), 0.0))
            model += (
                pulp.lpSum(
                    state_in[(s, d, r, t)]
                    for d in D
                    for t in T
                    if (s, d, r, t) in state_in
                ) <= cap,
                f"state_stock_total_{s}_{r}",
            )
            model += (
                pulp.lpSum(
                    state_in[(s, d, r, t)]
                    for d in D
                    for t in T
                    if (s, d, r, t) in state_in and str(state_for_d[str(d)]) != str(s)
                ) <= (cap * float(neighbor_stock_utilization_cap)),
                f"neighbor_export_cap_{s}_{r}",
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

    def _slot_priority_weight(d: str, r: str, t: int) -> float:
        p = float(priority_lookup.get((str(d), str(r), int(t)), 1.0) or 1.0)
        u = float(urgency_lookup.get((str(d), str(r), int(t)), 1.0) or 1.0)
        ti = float(time_index_lookup.get((str(d), str(r), int(t)), 1.0) or 1.0)
        p = max(0.5, min(5.0, p))
        u = max(0.5, min(5.0, u))
        ti = max(0.0, min(5.0, ti))
        return (0.50 + 0.50 * p) * (0.50 + 0.50 * u) * (1.0 + 0.10 * ti)

    district_flow_cost = 1.0
    state_flow_cost = 2.0
    neighbor_flow_cost = 2.3
    national_flow_cost = 3.0

    model += (
        pulp.lpSum(
            float(w_unmet)
            * _time_unmet_weight(t)
            * _slot_priority_weight(d, r, t)
            * var
            for (d, r, t), var in unmet.items()
        )
        + pulp.lpSum(float(w_hold) * var for (d, r, t), var in inv.items() if int(t) in T)
        + pulp.lpSum(district_flow_cost * var for (_, _, _), var in alloc_district.items())
        + pulp.lpSum(
            (state_flow_cost if str(origin_state) == str(state_for_d[str(d)]) else neighbor_flow_cost) * var
            for (origin_state, d, _, _), var in alloc_state_by_origin.items()
        )
        + pulp.lpSum(national_flow_cost * var for (_, _, _), var in alloc_national.items())
        + pulp.lpSum(float(w_ship) * var for (_, _, _, _), var in ship.items())
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
        "state_adjacency": {k: sorted(list(v)) for k, v in adjacency.items()},
    }

    variables = {
        "inventory": inv,
        "shipments": ship,
        "state_in": state_in,
        "national_in": nat_in,
        "allocation": alloc,
        "allocation_district": alloc_district,
        "allocation_state_by_origin": alloc_state_by_origin,
        "allocation_national": alloc_national,
        "unmet": unmet,
    }

    return model, metadata, variables
