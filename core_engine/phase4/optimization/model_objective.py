import pulp


def add_objective(model, x, u, demand_df=None):
    unmet_penalty = 1_000_000.0
    level_flow_cost = {
        "district": 1.0,
        "state": 2.0,
        "national": 3.0,
    }

    slot_weights: dict[tuple[str, str, int], float] = {}
    if demand_df is not None and not demand_df.empty:
        cols = set(demand_df.columns)
        for row in demand_df.itertuples(index=False):
            district = str(getattr(row, "district_code"))
            resource = str(getattr(row, "resource_id"))
            time = int(getattr(row, "time"))

            p = float(getattr(row, "priority", 1.0) if "priority" in cols else 1.0)
            u_w = float(getattr(row, "urgency", 1.0) if "urgency" in cols else 1.0)
            ti = float(getattr(row, "time_index", 1.0) if "time_index" in cols else 1.0)

            p = max(0.5, min(5.0, p))
            u_w = max(0.5, min(5.0, u_w))
            ti = max(0.0, min(5.0, ti))
            slot_weights[(resource, district, time)] = (0.50 + 0.50 * p) * (0.50 + 0.50 * u_w) * (1.0 + 0.10 * ti)

    unmet_term = pulp.lpSum(
        unmet_penalty * float(slot_weights.get((str(r), str(d), int(t)), 1.0)) * var
        for (r, d, t), var in u.items()
    )
    flow_term = pulp.lpSum(
        level_flow_cost.get(level, 1.0) * var
        for (level, _, _, _, _), var in x.items()
    )

    model += unmet_term + flow_term