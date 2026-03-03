# core_engine/phase4/optimization/model_variables.py

import pulp


def build_flow_variables(
    model,
    districts,
    states,
    resources,
    levels,
    times,
    district_to_state
):
    """
    Builds decision variables:

        x[(level, resource, state, district, time)]
        u[(resource, district, time)]

    Naming format is locked to match just_runs_cbc.py parser.
    """

    x = {}
    u = {}

    # -------------------------------------------------
    # FLOW VARIABLES
    # -------------------------------------------------

    for l in levels:
        for r in resources:
            for d in districts:
                mapped_state = district_to_state.get(d)
                if mapped_state is None:
                    continue

                for t in times:
                    if l in ("district", "state", "national"):
                        s_values = [mapped_state]
                    else:
                        s_values = states

                    for s in s_values:
                        var_name = f"x_{l}_{r}_{s}_{d}_{t}"

                        x[(l, r, s, d, t)] = pulp.LpVariable(
                            var_name,
                            lowBound=0,
                            cat="Continuous"
                        )

    # -------------------------------------------------
    # UNMET DEMAND VARIABLES
    # -------------------------------------------------

    for r in resources:
        for d in districts:
            for t in times:

                var_name = f"u_{r}_{d}_{t}"

                u[(r, d, t)] = pulp.LpVariable(
                    var_name,
                    lowBound=0,
                    cat="Continuous"
                )

    return x, u
