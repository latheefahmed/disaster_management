import pulp


def _build_lookup(df, key_cols, value_col):
    if df is None or df.empty:
        return {}

    out = {}
    cols = set(df.columns)

    if not set(key_cols).issubset(cols) or value_col not in cols:
        return out

    for row in df[key_cols + [value_col]].itertuples(index=False, name=None):
        *keys, value = row
        normalized = []
        for key_name, key_value in zip(key_cols, keys):
            if key_name == "time":
                normalized.append(int(key_value))
            else:
                normalized.append(str(key_value))
        out[tuple(normalized)] = float(value)
    return out


def add_demand_constraints(model, demand_df, x, u, D, S, R, L, T):
    demand_lookup = _build_lookup(
        demand_df,
        ["resource_id", "district_code", "time"],
        "demand"
    )

    for r in R:
        for d in D:
            for t in T:
                demand = demand_lookup.get((str(r), str(d), int(t)), 0.0)

                flow_terms = [
                    x[(l, r, s, d, t)]
                    for l in L
                    for s in S
                    if (l, r, s, d, t) in x
                ]

                model += (
                    pulp.lpSum(flow_terms) + u[(r, d, t)] == demand,
                    f"demand_{r}_{d}_{t}"
                )


def add_district_stock_constraints(model, district_stock_df, x, D, R, S, T):
    district_stock_lookup = _build_lookup(
        district_stock_df,
        ["district_code", "resource_id"],
        "quantity"
    )

    for d in D:
        for r in R:
            cap = float(district_stock_lookup.get((str(d), str(r)), 0.0))

            for t in T:
                flow_terms = [
                    x[("district", r, s, d, t)]
                    for s in S
                    if ("district", r, s, d, t) in x
                ]

                model += (
                    pulp.lpSum(flow_terms) <= cap,
                    f"district_stock_{r}_{d}_{t}"
                )


def add_state_stock_constraints(model, state_stock_df, x, D, R, S, T, district_to_state):
    state_stock_lookup = _build_lookup(
        state_stock_df,
        ["state_code", "resource_id"],
        "quantity"
    )

    for s in S:
        ds = [d for d in D if district_to_state.get(d) == s]

        for r in R:
            cap = float(state_stock_lookup.get((str(s), str(r)), 0.0))

            for t in T:
                flow_terms = [
                    x[("state", r, s, d, t)]
                    for d in ds
                    if ("state", r, s, d, t) in x
                ]

                model += (
                    pulp.lpSum(flow_terms) <= cap,
                    f"state_stock_{r}_{s}_{t}"
                )


def add_national_stock_constraints(model, national_stock_df, x, D, R, S, T):
    national_stock_lookup = _build_lookup(
        national_stock_df,
        ["resource_id"],
        "quantity"
    )

    for r in R:
        cap = float(national_stock_lookup.get((str(r),), 0.0))

        for t in T:
            flow_terms = [
                x[("national", r, s, d, t)]
                for s in S
                for d in D
                if ("national", r, s, d, t) in x
            ]

            model += (
                pulp.lpSum(flow_terms) <= cap,
                f"national_stock_{r}_{t}"
            )


def add_flow_validity_constraints(model, x, D, R, S, T, district_to_state):
    for (l, r, s, d, t), var in x.items():
        if l == "district" and district_to_state.get(d) != s:
            model += (var == 0, f"flow_validity_district_{r}_{s}_{d}_{t}")
        elif l == "state" and district_to_state.get(d) != s:
            model += (var == 0, f"flow_validity_state_{r}_{s}_{d}_{t}")
