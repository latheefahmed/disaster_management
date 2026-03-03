import argparse
import pulp
import pandas as pd
import os
import json

from build_model_cbc import build_model_cbc
from build_model_phase8 import build_model_phase8

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "output")


def parse_x(name):
    parts = name.split("_")

    level = parts[1]
    time = parts[-1]
    district = parts[-2]
    state = parts[-3]
    resource = "_".join(parts[2:-3])

    return level, resource, state, district, time


def parse_u(name):
    parts = name.split("_")

    time = parts[-1]
    district = parts[-2]
    resource = "_".join(parts[1:-2])

    return resource, district, time


def _write_unmet_csv(out_dir, unmet_rows):
    unmet_df = pd.DataFrame(
        unmet_rows,
        columns=[
            "resource_id",
            "district_code",
            "time",
            "unmet_quantity",
        ],
    )

    unmet_df.to_csv(
        os.path.join(out_dir, "unmet_demand_u.csv"),
        index=False
    )
    unmet_df.to_csv(
        os.path.join(out_dir, "unmet_u.csv"),
        index=False
    )


def _write_inventory_csv(out_dir, inventory_rows):
    pd.DataFrame(
        inventory_rows,
        columns=[
            "district_code",
            "resource_id",
            "time",
            "quantity",
        ],
    ).to_csv(
        os.path.join(out_dir, "inventory_t.csv"),
        index=False,
    )


def _write_shipment_csv(out_dir, shipment_rows):
    pd.DataFrame(
        shipment_rows,
        columns=[
            "from_district",
            "to_district",
            "resource_id",
            "time",
            "quantity",
            "status",
        ],
    ).to_csv(
        os.path.join(out_dir, "shipment_plan.csv"),
        index=False,
    )


def _write_allocation_csv(out_dir, alloc_rows):
    pd.DataFrame(
        alloc_rows,
        columns=[
            "supply_level",
            "resource_id",
            "state_code",
            "district_code",
            "time",
            "allocated_quantity",
        ],
    ).to_csv(
        os.path.join(out_dir, "allocation_x.csv"),
        index=False,
    )


def _write_run_summary(out_dir, run_summary):
    summary_path = os.path.join(out_dir, "run_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(run_summary, f, indent=2)


def _solve_with_cbc(model, cbc_time_limit: int):
    solver = pulp.PULP_CBC_CMD(msg=True, timeLimit=max(1, int(cbc_time_limit)))
    model.solve(solver)
    status = str(pulp.LpStatus.get(model.status, model.status))
    has_values = any(v.varValue is not None for v in model.variables())
    print("SOLVER_STATUS", status)
    print("HAS_FEASIBLE_VALUES", has_values)
    return status, has_values


def _solve_single_step_legacy(args):
    model = build_model_cbc(
        demand_override_path=args.demand_override,
        district_stock_override_path=args.district_stock_override,
        state_stock_override_path=args.state_stock_override,
        national_stock_override_path=args.national_stock_override,
        horizon=args.horizon,
    )

    status, has_values = _solve_with_cbc(model, args.cbc_time_limit)
    if status in {"Infeasible", "Undefined"} and not has_values:
        raise RuntimeError(f"CBC failed without feasible solution: status={status}")

    print("Status:", pulp.LpStatus[model.status])
    print("Objective:", pulp.value(model.objective))

    alloc_rows = []
    unmet_rows = []

    for v in model.variables():
        val = 0.0 if v.varValue is None else float(v.varValue)
        if val == 0:
            continue

        name = v.name

        if name.startswith("x_"):
            level, resource, state, district, time = parse_x(name)

            alloc_rows.append({
                "supply_level": level,
                "resource_id": resource,
                "state_code": state,
                "district_code": district,
                "time": int(time),
                "allocated_quantity": val
            })

        elif name.startswith("u_"):
            resource, district, time = parse_u(name)

            unmet_rows.append({
                "resource_id": resource,
                "district_code": district,
                "time": int(time),
                "unmet_quantity": val
            })

    _write_allocation_csv(OUT_DIR, alloc_rows)
    _write_unmet_csv(OUT_DIR, unmet_rows)
    _write_inventory_csv(OUT_DIR, [])
    _write_shipment_csv(OUT_DIR, [])

    print("Written allocation rows:", len(alloc_rows))
    print("Written unmet rows:", len(unmet_rows))

    total_alloc = float(sum(float(r["allocated_quantity"]) for r in alloc_rows)) if alloc_rows else 0.0
    total_unmet = float(sum(float(r["unmet_quantity"]) for r in unmet_rows)) if unmet_rows else 0.0

    demand_total = total_alloc + total_unmet

    districts = sorted({str(r["district_code"]) for r in alloc_rows} | {str(r["district_code"]) for r in unmet_rows})
    resources = sorted({str(r["resource_id"]) for r in alloc_rows} | {str(r["resource_id"]) for r in unmet_rows})
    time_steps = sorted({int(r["time"]) for r in alloc_rows} | {int(r["time"]) for r in unmet_rows})

    run_summary = {
        "districts": len(districts),
        "resources": len(resources),
        "time_steps": len(time_steps),
        "horizon": 1,
        "rolling": False,
        "total_demand": demand_total,
        "total_stock": total_alloc,
        "total_unmet": total_unmet,
        "objective": float(pulp.value(model.objective) or 0.0),
        "status": str(pulp.LpStatus[model.status]),
    }

    _write_run_summary(OUT_DIR, run_summary)
    print("Run summary:", run_summary)


def _collect_phase8_rows(metadata, variables, execute_times=None):
    state_for_d = metadata["state_for_district"]
    T = metadata["times"]
    selected_times = set(T if execute_times is None else execute_times)

    alloc_rows = []
    unmet_rows = []
    inventory_rows = []
    shipment_rows = []

    for (d, r, t), var in variables["allocation_district"].items():
        if int(t) not in selected_times:
            continue
        val = 0.0 if var.varValue is None else float(var.varValue)
        if val <= 0:
            continue
        alloc_rows.append({
            "supply_level": "district",
            "resource_id": str(r),
            "state_code": str(state_for_d[str(d)]),
            "district_code": str(d),
            "time": int(t),
            "allocated_quantity": val,
        })

    for (d, r, t), var in variables["allocation_state"].items():
        if int(t) not in selected_times:
            continue
        val = 0.0 if var.varValue is None else float(var.varValue)
        if val <= 0:
            continue
        alloc_rows.append({
            "supply_level": "state",
            "resource_id": str(r),
            "state_code": str(state_for_d[str(d)]),
            "district_code": str(d),
            "time": int(t),
            "allocated_quantity": val,
        })

    for (d, r, t), var in variables["allocation_national"].items():
        if int(t) not in selected_times:
            continue
        val = 0.0 if var.varValue is None else float(var.varValue)
        if val <= 0:
            continue
        alloc_rows.append({
            "supply_level": "national",
            "resource_id": str(r),
            "state_code": str(state_for_d[str(d)]),
            "district_code": str(d),
            "time": int(t),
            "allocated_quantity": val,
        })

    for (d, r, t), var in variables["unmet"].items():
        if int(t) not in selected_times:
            continue
        val = 0.0 if var.varValue is None else float(var.varValue)
        if val <= 0:
            continue
        unmet_rows.append({
            "resource_id": str(r),
            "district_code": str(d),
            "time": int(t),
            "unmet_quantity": val,
        })

    for (d, r, t), var in variables["inventory"].items():
        val = 0.0 if var.varValue is None else float(var.varValue)
        inventory_rows.append({
            "district_code": str(d),
            "resource_id": str(r),
            "time": int(t),
            "quantity": max(0.0, val),
        })

    for (f, to, r, t), var in variables["shipments"].items():
        if int(t) not in selected_times:
            continue
        val = 0.0 if var.varValue is None else float(var.varValue)
        if val <= 0:
            continue
        shipment_rows.append({
            "from_district": str(f),
            "to_district": str(to),
            "resource_id": str(r),
            "time": int(t),
            "quantity": val,
            "status": "planned",
        })

    for (d, r, t), var in variables["state_in"].items():
        if int(t) not in selected_times:
            continue
        val = 0.0 if var.varValue is None else float(var.varValue)
        if val <= 0:
            continue
        shipment_rows.append({
            "from_district": f"STATE::{state_for_d[str(d)]}",
            "to_district": str(d),
            "resource_id": str(r),
            "time": int(t),
            "quantity": val,
            "status": "planned",
        })

    for (d, r, t), var in variables["national_in"].items():
        if int(t) not in selected_times:
            continue
        val = 0.0 if var.varValue is None else float(var.varValue)
        if val <= 0:
            continue
        shipment_rows.append({
            "from_district": "NATIONAL",
            "to_district": str(d),
            "resource_id": str(r),
            "time": int(t),
            "quantity": val,
            "status": "planned",
        })

    return alloc_rows, unmet_rows, inventory_rows, shipment_rows


def _solve_phase8_window(args, current_time=None):
    model, metadata, variables = build_model_phase8(
        demand_override_path=args.demand_override,
        district_stock_override_path=args.district_stock_override,
        state_stock_override_path=args.state_stock_override,
        national_stock_override_path=args.national_stock_override,
        current_time=current_time if current_time is not None else args.current_time,
        horizon=args.horizon,
        w_unmet=args.w_unmet,
        w_hold=args.w_hold,
        w_ship=args.w_ship,
    )
    status, has_values = _solve_with_cbc(model, args.cbc_time_limit)
    if status in {"Infeasible", "Undefined"} and not has_values:
        raise RuntimeError(f"CBC failed without feasible solution: status={status}")
    return model, metadata, variables


def _write_phase8_outputs(out_dir, alloc_rows, unmet_rows, inventory_rows, shipment_rows):
    _write_allocation_csv(out_dir, alloc_rows)
    _write_unmet_csv(out_dir, unmet_rows)
    _write_inventory_csv(out_dir, inventory_rows)
    _write_shipment_csv(out_dir, shipment_rows)


def _solve_phase8_single_window(args):
    model, metadata, variables = _solve_phase8_window(args)
    alloc_rows, unmet_rows, inventory_rows, shipment_rows = _collect_phase8_rows(metadata, variables)
    _write_phase8_outputs(OUT_DIR, alloc_rows, unmet_rows, inventory_rows, shipment_rows)

    total_alloc = float(sum(float(r["allocated_quantity"]) for r in alloc_rows)) if alloc_rows else 0.0
    total_unmet = float(sum(float(r["unmet_quantity"]) for r in unmet_rows)) if unmet_rows else 0.0
    total_demand = total_alloc + total_unmet

    run_summary = {
        "districts": len(metadata["districts"]),
        "resources": len(metadata["resources"]),
        "time_steps": len(metadata["times"]),
        "horizon": int(args.horizon),
        "rolling": False,
        "window_start": int(metadata["window_start"]),
        "window_end": int(metadata["window_end"]),
        "total_demand": total_demand,
        "total_stock": total_alloc,
        "total_unmet": total_unmet,
        "objective": float(pulp.value(model.objective) or 0.0),
        "status": str(pulp.LpStatus[model.status]),
    }
    _write_run_summary(OUT_DIR, run_summary)
    print("Run summary:", run_summary)


def _build_district_stock_override_from_inventory(inventory_rows, next_time):
    rows = [
        {
            "district_code": r["district_code"],
            "resource_id": r["resource_id"],
            "quantity": float(r["quantity"]),
        }
        for r in inventory_rows
        if int(r["time"]) == int(next_time)
    ]
    path = os.path.join(OUT_DIR, f"rolling_district_stock_t{int(next_time)}.csv")
    pd.DataFrame(rows, columns=["district_code", "resource_id", "quantity"]).to_csv(path, index=False)
    return path


def _solve_phase8_rolling(args):
    from loaders import load_demand

    demand_df = load_demand(".", demand_override_path=args.demand_override)
    all_times = sorted(int(t) for t in demand_df["time"].astype(int).unique().tolist())
    if not all_times:
        raise ValueError("No demand rows for rolling horizon")

    start_time = int(args.current_time) if args.current_time is not None else int(all_times[0])
    exec_times = [t for t in all_times if t >= start_time]
    if not exec_times:
        raise ValueError("No time slots to execute in rolling horizon")

    accumulated_alloc = []
    accumulated_unmet = []
    accumulated_inventory = []
    accumulated_shipments = []
    objectives = []
    statuses = []

    district_stock_override = args.district_stock_override

    for current_t in exec_times:
        step_args = argparse.Namespace(**vars(args))
        step_args.current_time = int(current_t)
        step_args.district_stock_override = district_stock_override

        model, metadata, variables = _solve_phase8_window(step_args, current_time=current_t)
        alloc_rows, unmet_rows, inventory_rows, shipment_rows = _collect_phase8_rows(metadata, variables, execute_times={int(current_t)})

        accumulated_alloc.extend(alloc_rows)
        accumulated_unmet.extend(unmet_rows)
        accumulated_shipments.extend(shipment_rows)

        next_time = int(current_t) + 1
        step_inventory = [r for r in inventory_rows if int(r["time"]) in {int(current_t), int(next_time)}]
        accumulated_inventory.extend(step_inventory)

        district_stock_override = _build_district_stock_override_from_inventory(inventory_rows, next_time)
        objectives.append(float(pulp.value(model.objective) or 0.0))
        statuses.append(str(pulp.LpStatus[model.status]))

    _write_phase8_outputs(OUT_DIR, accumulated_alloc, accumulated_unmet, accumulated_inventory, accumulated_shipments)

    total_alloc = float(sum(float(r["allocated_quantity"]) for r in accumulated_alloc)) if accumulated_alloc else 0.0
    total_unmet = float(sum(float(r["unmet_quantity"]) for r in accumulated_unmet)) if accumulated_unmet else 0.0

    run_summary = {
        "districts": len(sorted({str(r["district_code"]) for r in accumulated_alloc} | {str(r["district_code"]) for r in accumulated_unmet})),
        "resources": len(sorted({str(r["resource_id"]) for r in accumulated_alloc} | {str(r["resource_id"]) for r in accumulated_unmet})),
        "time_steps": len(sorted({int(r["time"]) for r in accumulated_alloc} | {int(r["time"]) for r in accumulated_unmet})),
        "horizon": int(args.horizon),
        "rolling": True,
        "window_start": int(start_time),
        "window_end": int(exec_times[-1]),
        "total_demand": total_alloc + total_unmet,
        "total_stock": total_alloc,
        "total_unmet": total_unmet,
        "objective": float(sum(objectives)),
        "status": "Optimal" if all(s == "Optimal" for s in statuses) else "Suboptimal",
    }
    _write_run_summary(OUT_DIR, run_summary)
    print("Run summary:", run_summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demand", dest="demand_override")
    parser.add_argument("--district-stock", dest="district_stock_override")
    parser.add_argument("--state-stock", dest="state_stock_override")
    parser.add_argument("--national-stock", dest="national_stock_override")
    parser.add_argument("--horizon", type=int, default=30)
    parser.add_argument("--current-time", type=int, default=None)
    parser.add_argument("--rolling", action="store_true")
    parser.add_argument("--w-unmet", type=float, default=1_000_000.0)
    parser.add_argument("--w-hold", type=float, default=1.0)
    parser.add_argument("--w-ship", type=float, default=2.0)
    parser.add_argument("--cbc-time-limit", type=int, default=240)
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    if int(args.horizon) <= 1:
        _solve_single_step_legacy(args)
        return

    if args.rolling:
        _solve_phase8_rolling(args)
    else:
        _solve_phase8_single_window(args)


if __name__ == "__main__":
    main()
