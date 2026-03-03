from __future__ import annotations

from collections import defaultdict

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.allocation import Allocation
from app.models.final_demand import FinalDemand
from app.models.nn_feature_cache import NNFeatureCache
from app.models.request import ResourceRequest
from app.models.solver_run import SolverRun

FEATURE_COLUMNS = [
    "baseline_demand",
    "human_request_quantity",
    "unmet_ratio_last_run",
    "avg_unmet_last_5",
    "fill_rate_last_5",
    "avg_delay_last_5",
    "stock_ratio",
    "priority_avg",
    "urgency_avg",
    "recent_escalation_count",
]


def _latest_completed_run_ids(db: Session, limit: int = 30) -> list[int]:
    rows = db.query(SolverRun).filter(
        SolverRun.mode == "live",
        SolverRun.status == "completed",
    ).order_by(SolverRun.id.desc()).limit(max(1, int(limit))).all()
    return [int(r.id) for r in rows]


def _normalize_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        series = out[col].astype(float)
        min_v = float(series.min()) if not series.empty else 0.0
        max_v = float(series.max()) if not series.empty else 0.0
        if abs(max_v - min_v) <= 1e-9:
            out[col] = 0.0
        else:
            out[col] = (series - min_v) / (max_v - min_v)
    return out


def build_feature_vectors(
    db: Session,
    base_df: pd.DataFrame,
    human_df: pd.DataFrame,
    solver_run_id: int | None,
    window: int = 30,
) -> pd.DataFrame:
    base = base_df.copy()
    human = human_df.copy()

    if base.empty:
        base = pd.DataFrame(columns=["district_code", "resource_id", "time", "demand"])
    if human.empty:
        human = pd.DataFrame(columns=["district_code", "resource_id", "time", "demand"])

    base = base.rename(columns={"demand": "baseline_demand"})
    human = human.rename(columns={"demand": "human_request_quantity"})

    merged = base.merge(human, on=["district_code", "resource_id", "time"], how="outer")
    merged["baseline_demand"] = merged["baseline_demand"].fillna(0.0)
    merged["human_request_quantity"] = merged["human_request_quantity"].fillna(0.0)

    run_ids = _latest_completed_run_ids(db, limit=max(5, int(window)))
    last_run = run_ids[0] if run_ids else None
    last5 = run_ids[:5]

    unmet_last: dict[tuple[str, str], float] = defaultdict(float)
    total_last: dict[tuple[str, str], float] = defaultdict(float)
    avg_unmet_5: dict[tuple[str, str], float] = defaultdict(float)
    fill_rate_5: dict[tuple[str, str], float] = defaultdict(float)
    delay_5: dict[tuple[str, str], float] = defaultdict(float)
    delay_count_5: dict[tuple[str, str], int] = defaultdict(int)

    if last_run is not None:
        demand_rows = db.query(
            FinalDemand.district_code,
            FinalDemand.resource_id,
            func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0).label("demand_total"),
        ).filter(
            FinalDemand.solver_run_id == int(last_run)
        ).group_by(
            FinalDemand.district_code,
            FinalDemand.resource_id,
        ).all()
        for row in demand_rows:
            key = (str(row.district_code), str(row.resource_id))
            total_last[key] += float(row.demand_total or 0.0)

        rows = db.query(Allocation).filter(Allocation.solver_run_id == int(last_run)).all()
        for row in rows:
            key = (str(row.district_code), str(row.resource_id))
            qty = float(row.allocated_quantity or 0.0)
            if bool(row.is_unmet):
                unmet_last[key] += qty

    if last5:
        demand_rows = db.query(
            FinalDemand.solver_run_id,
            FinalDemand.district_code,
            FinalDemand.resource_id,
            func.coalesce(func.sum(FinalDemand.demand_quantity), 0.0).label("demand_total"),
        ).filter(
            FinalDemand.solver_run_id.in_(last5)
        ).group_by(
            FinalDemand.solver_run_id,
            FinalDemand.district_code,
            FinalDemand.resource_id,
        ).all()

        demand_den_by_run_key: dict[tuple[int, str, str], float] = {}
        for row in demand_rows:
            demand_den_by_run_key[(int(row.solver_run_id), str(row.district_code), str(row.resource_id))] = float(row.demand_total or 0.0)

        rows = db.query(Allocation).filter(Allocation.solver_run_id.in_(last5)).all()
        unmet_tmp: dict[tuple[str, str], list[float]] = defaultdict(list)
        fill_tmp_num: dict[tuple[str, str], float] = defaultdict(float)
        fill_tmp_den: dict[tuple[str, str], float] = defaultdict(float)
        seen_den_keys: set[tuple[int, str, str]] = set()

        for run_id, district, resource in demand_den_by_run_key.keys():
            key = (district, resource)
            fill_tmp_den[key] += float(demand_den_by_run_key[(run_id, district, resource)])
            seen_den_keys.add((run_id, district, resource))

        for row in rows:
            key = (str(row.district_code), str(row.resource_id))
            qty = float(row.allocated_quantity or 0.0)
            if bool(row.is_unmet):
                unmet_tmp[key].append(qty)
            else:
                unmet_tmp[key].append(0.0)
                fill_tmp_num[key] += qty

            if bool(row.receipt_confirmed) and row.receipt_time is not None and row.created_at is not None:
                delta = row.receipt_time - row.created_at
                delay_5[key] += max(0.0, float(delta.total_seconds()) / 3600.0)
                delay_count_5[key] += 1

        for key, vals in unmet_tmp.items():
            avg_unmet_5[key] = float(sum(vals)) / max(1, len(vals))
            den = float(fill_tmp_den[key])
            fill_rate_5[key] = 0.0 if den <= 1e-9 else float(fill_tmp_num[key]) / den

    priority_avg: dict[tuple[str, str], float] = defaultdict(float)
    urgency_avg: dict[tuple[str, str], float] = defaultdict(float)
    escalation_count: dict[tuple[str, str], int] = defaultdict(int)

    req_rows = db.query(ResourceRequest).all()
    req_count_p: dict[tuple[str, str], int] = defaultdict(int)
    req_count_u: dict[tuple[str, str], int] = defaultdict(int)
    for row in req_rows:
        key = (str(row.district_code), str(row.resource_id))
        if row.priority is not None:
            priority_avg[key] += float(row.priority)
            req_count_p[key] += 1
        if row.urgency is not None:
            urgency_avg[key] += float(row.urgency)
            req_count_u[key] += 1
        if str(row.status) == "escalated_national":
            escalation_count[key] += 1

    for key in list(priority_avg.keys()):
        priority_avg[key] = float(priority_avg[key]) / max(1, req_count_p[key])
    for key in list(urgency_avg.keys()):
        urgency_avg[key] = float(urgency_avg[key]) / max(1, req_count_u[key])

    rows_out = []
    for row in merged.itertuples(index=False):
        district = str(row.district_code)
        resource = str(row.resource_id)
        time = int(row.time)
        key = (district, resource)

        total = float(total_last[key])
        unmet_ratio_last_run = 0.0 if total <= 1e-9 else float(unmet_last[key]) / total
        avg_delay = 0.0 if delay_count_5[key] <= 0 else float(delay_5[key]) / float(delay_count_5[key])
        stock_ratio = 0.0 if float(row.baseline_demand) <= 1e-9 else max(0.0, float(total) / float(row.baseline_demand))

        rows_out.append({
            "district_code": district,
            "resource_id": resource,
            "time": time,
            "baseline_demand": float(row.baseline_demand),
            "human_request_quantity": float(row.human_request_quantity),
            "unmet_ratio_last_run": float(unmet_ratio_last_run),
            "avg_unmet_last_5": float(avg_unmet_5[key]),
            "fill_rate_last_5": float(fill_rate_5[key]),
            "avg_delay_last_5": float(avg_delay),
            "stock_ratio": float(stock_ratio),
            "priority_avg": float(priority_avg[key]),
            "urgency_avg": float(urgency_avg[key]),
            "recent_escalation_count": int(escalation_count[key]),
        })

    out = pd.DataFrame(rows_out)
    if out.empty:
        return out

    norm = _normalize_frame(out, FEATURE_COLUMNS)

    if solver_run_id is not None:
        db.query(NNFeatureCache).filter(NNFeatureCache.solver_run_id == int(solver_run_id)).delete(synchronize_session=False)
        for row_raw, row_norm in zip(out.to_dict(orient="records"), norm.to_dict(orient="records")):
            db.add(NNFeatureCache(
                solver_run_id=int(solver_run_id),
                district_code=str(row_raw["district_code"]),
                resource_id=str(row_raw["resource_id"]),
                time=int(row_raw["time"]),
                raw_features_json={k: row_raw[k] for k in FEATURE_COLUMNS},
                norm_features_json={k: row_norm[k] for k in FEATURE_COLUMNS},
            ))
        db.flush()

    for col in FEATURE_COLUMNS:
        out[f"norm_{col}"] = norm[col]

    return out
