import pulp


def add_objective(model, x, u):
    unmet_penalty = 1_000_000.0
    priority_weight = 1.0
    urgency_weight = 1.0
    level_flow_cost = {
        "district": 1.0,
        "state": 2.0,
        "national": 3.0,
    }

    unmet_term = pulp.lpSum(unmet_penalty * priority_weight * urgency_weight * var for var in u.values())
    flow_term = pulp.lpSum(
        level_flow_cost.get(level, 1.0) * var
        for (level, _, _, _, _), var in x.items()
    )

    model += unmet_term + flow_term