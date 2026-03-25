from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from app.database import SessionLocal
from app.models.solver_run import SolverRun

BASE = "http://127.0.0.1:8000"
REPORT_PATH = Path("MULTI_STATE_POPULATION_VERIFY_REPORT.json")
PASSWORD_CANDIDATES = {
    "national": ["national123", "pw", "admin123", "password"],
    "state": ["state123", "pw", "password"],
    "district": ["district123", "pw"],
}


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def login_with_candidates(usernames: list[str], passwords: list[str]) -> tuple[str, str, str]:
    errs: list[str] = []
    for username in usernames:
        for password in passwords:
            try:
                r = requests.post(
                    f"{BASE}/auth/login",
                    json={"username": username, "password": password},
                    timeout=30,
                )
                if r.status_code == 200:
                    payload = r.json()
                    token = str(payload.get("access_token") or "")
                    if token:
                        return username, password, token
                errs.append(f"{username}/{password}:{r.status_code}")
            except Exception as exc:
                errs.append(f"{username}/{password}:{type(exc).__name__}:{exc}")
    raise RuntimeError("Unable to authenticate: " + "; ".join(errs[-8:]))


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_json(path: str, token: str | None = None, params: dict[str, Any] | None = None) -> Any:
    h = headers(token) if token else {}
    r = requests.get(f"{BASE}{path}", headers=h, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def post_json(path: str, token: str, payload: dict[str, Any]) -> tuple[int, Any]:
    r = requests.post(f"{BASE}{path}", headers=headers(token), json=payload, timeout=60)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    return r.status_code, body


def fetch_allocation_summary_pages(path: str, token: str, page_size: int = 200) -> dict[str, Any]:
    page = 1
    rows_accum: list[dict[str, Any]] = []
    while True:
        payload = get_json(path, token=token, params={"page": page, "page_size": page_size})
        rows = list((payload or {}).get("rows") or [])
        if not rows:
            break
        rows_accum.extend(rows)
        if len(rows) < page_size:
            break
        page += 1

    states = sorted({str(r.get("state_code") or "") for r in rows_accum if r.get("state_code") is not None})
    districts = sorted({str(r.get("district_code") or "") for r in rows_accum if r.get("district_code") is not None})

    return {
        "total_rows": len(rows_accum),
        "unique_states_count": len(states),
        "unique_districts_count": len(districts),
        "unique_states": states,
        "unique_districts": districts,
    }


def poll_run_row(run_id: int, timeout_s: int = 240) -> dict[str, Any]:
    started = time.time()
    last: SolverRun | None = None
    while time.time() - started < timeout_s:
        with SessionLocal() as db:
            row = db.query(SolverRun).filter(SolverRun.id == int(run_id)).first()
            if row is not None:
                last = row
                status = str(row.status or "").lower()
                if status in {"completed", "failed"}:
                    break
        time.sleep(2)

    if last is None:
        return {"solver_run_id": int(run_id), "status": "missing"}

    reason = ""
    summary = getattr(last, "summary_snapshot_json", None)
    if summary:
        try:
            parsed = json.loads(str(summary))
            reason = str(parsed.get("failure_reason") or parsed.get("error") or "")
        except Exception:
            reason = str(summary)

    return {
        "solver_run_id": int(last.id),
        "status": str(last.status or ""),
        "failure_reason": reason,
        "summary_snapshot_json": str(summary) if summary is not None else None,
    }


def main() -> None:
    report: dict[str, Any] = {
        "started_at": now_iso(),
        "base": BASE,
    }

    national_user, national_pw, national_token = login_with_candidates(
        ["national_admin", "national_user"], PASSWORD_CANDIDATES["national"]
    )
    report["auth"] = {"national_user": national_user, "national_password": national_pw}

    states = list(get_json("/metadata/states"))
    districts = list(get_json("/metadata/districts"))
    resources = list(get_json("/metadata/resources"))

    state_codes_all = [str(s.get("state_code") or "").zfill(2) for s in states]
    if "33" not in state_codes_all:
        raise RuntimeError("Required state 33 not present in metadata")

    selected_states: list[str] = ["33"]
    for code in state_codes_all:
        if code != "33":
            selected_states.append(code)
        if len(selected_states) >= 3:
            break
    selected_states = selected_states[:3]

    grouped_districts: dict[str, list[str]] = defaultdict(list)
    for d in districts:
        state_code = str(d.get("state_code") or "").zfill(2)
        district_code = str(d.get("district_code") or "")
        if district_code:
            grouped_districts[state_code].append(district_code)

    resource_ids = [str(r.get("resource_id") or "") for r in resources if str(r.get("resource_id") or "")]
    if len(resource_ids) < 3:
        raise RuntimeError("Need at least 3 resources in metadata")
    picked_resources = resource_ids[:3]

    state_tokens: dict[str, str] = {}
    state_auth_rows: list[dict[str, Any]] = []
    for sc in selected_states:
        uname, pw, token = login_with_candidates([f"state_{int(sc)}", f"state_{sc}"], PASSWORD_CANDIDATES["state"])
        state_tokens[sc] = token
        state_auth_rows.append({"state_code": sc, "username": uname, "password": pw})
    report["state_auth"] = state_auth_rows

    population_rows: list[dict[str, Any]] = []
    created_count_total = 0
    failures: list[dict[str, Any]] = []
    solver_run_ids: list[int] = []

    qty_matrix = [40, 120, 260]

    for sc in selected_states:
        candidates = sorted(set(grouped_districts.get(sc, [])))[:3]
        if len(candidates) < 3:
            failures.append({"state_code": sc, "error": "Not enough districts for state"})
            continue

        for idx, district_code in enumerate(candidates):
            usernames = [f"district_{district_code}"]
            try:
                d_user, d_pw, d_token = login_with_candidates(usernames, PASSWORD_CANDIDATES["district"])
            except Exception as exc:
                failures.append({
                    "state_code": sc,
                    "district_code": district_code,
                    "error": f"district login failed: {exc}",
                })
                continue

            items = [
                {
                    "resource_id": picked_resources[0],
                    "quantity": qty_matrix[idx % 3],
                    "time": 1,
                    "source": "human",
                },
                {
                    "resource_id": picked_resources[1],
                    "quantity": qty_matrix[(idx + 1) % 3] + 20,
                    "time": 2,
                    "source": "human",
                },
                {
                    "resource_id": picked_resources[2],
                    "quantity": qty_matrix[(idx + 2) % 3] + 50,
                    "time": 3,
                    "source": "human",
                },
            ]

            code, body = post_json("/district/request-batch", d_token, {"items": items})
            row = {
                "state_code": sc,
                "district_code": district_code,
                "district_user": d_user,
                "district_password": d_pw,
                "status_code": int(code),
                "response": body,
            }
            population_rows.append(row)

            if int(code) == 200 and isinstance(body, dict):
                req_ids = list(body.get("request_ids") or [])
                created_count_total += len(req_ids)
                run_id = int(body.get("solver_run_id") or 0)
                if run_id > 0:
                    solver_run_ids.append(run_id)
            else:
                failures.append({
                    "state_code": sc,
                    "district_code": district_code,
                    "error": f"request-batch failed: {code}",
                    "response": body,
                })

    report["population"] = {
        "selected_states": selected_states,
        "picked_resources": picked_resources,
        "rows": population_rows,
        "created_request_count_total": int(created_count_total),
        "failures": failures,
        "solver_run_ids": sorted(set(solver_run_ids)),
    }

    latest_run_id = max(solver_run_ids) if solver_run_ids else 0
    if latest_run_id <= 0:
        # explicit trigger fallback from one known district user from successful population
        success_row = next((r for r in population_rows if int(r.get("status_code") or 0) == 200), None)
        if success_row is None:
            raise RuntimeError("No successful district request-batch to trigger live run")
        d_user = str(success_row["district_user"])
        d_pw = str(success_row["district_password"])
        _u, _p, d_token = login_with_candidates([d_user], [d_pw])
        code, body = post_json("/district/run", d_token, {})
        if code != 200:
            raise RuntimeError(f"/district/run failed: {code} {body}")
        latest_run_id = int((body or {}).get("solver_run_id") or 0)

    run_row = poll_run_row(latest_run_id, timeout_s=300)

    if str(run_row.get("status") or "").lower() == "failed":
        reason = str(run_row.get("failure_reason") or "")
        if "not JSON serializable" in reason:
            success_row = next((r for r in population_rows if int(r.get("status_code") or 0) == 200), None)
            if success_row is not None:
                _u, _p, d_token = login_with_candidates([str(success_row["district_user"])], [str(success_row["district_password"])])
                code, body = post_json("/district/run", d_token, {})
                if code == 200:
                    retry_run_id = int((body or {}).get("solver_run_id") or 0)
                    if retry_run_id > 0:
                        run_row = poll_run_row(retry_run_id, timeout_s=300)
                        latest_run_id = retry_run_id

    report["latest_live_run"] = run_row

    national_kpi = get_json("/national/kpis", token=national_token)
    report["national_kpi"] = national_kpi

    state_kpis: dict[str, Any] = {}
    for sc in selected_states:
        token = state_tokens.get(sc)
        if token:
            state_kpis[sc] = get_json("/state/kpis", token=token)
    report["state_kpis"] = state_kpis

    nat_summary_stats = fetch_allocation_summary_pages("/national/allocations/summary", national_token, page_size=200)
    report["pagination_national"] = nat_summary_stats

    state_summary_stats: dict[str, Any] = {}
    for sc in selected_states:
        token = state_tokens.get(sc)
        if token:
            state_summary_stats[sc] = fetch_allocation_summary_pages("/state/allocations/summary", token, page_size=200)
    report["pagination_state"] = state_summary_stats

    # Mutual-aid auto-accept verification from market
    mutual_aid_check: dict[str, Any] = {
        "attempted": False,
        "offer_created": False,
        "offer_status": None,
        "pool_tx_sent_found": False,
        "pool_tx_received_found": False,
    }
    if len(selected_states) >= 2:
        offering_state = selected_states[1]
        token = state_tokens.get(offering_state)
        if token:
            market = list(get_json("/state/mutual-aid/market", token=token) or [])
            mutual_aid_check["attempted"] = True
            if market:
                row = market[0]
                req_id = int(row.get("id") or 0)
                qty = max(1.0, min(float(row.get("remaining_quantity") or 1.0), 5.0))
                code, body = post_json(
                    "/state/mutual-aid/offers",
                    token,
                    {"request_id": req_id, "quantity_offered": qty},
                )
                mutual_aid_check["offer_response_code"] = code
                mutual_aid_check["offer_response"] = body
                if code == 200 and isinstance(body, dict):
                    mutual_aid_check["offer_created"] = True
                    mutual_aid_check["offer_status"] = body.get("offer_status")
                    offer_id = int(body.get("offer_id") or 0)
                    tx_rows_offering = list(get_json("/state/pool/transactions", token=token, params={"limit": 200}) or [])
                    mutual_aid_check["pool_tx_sent_found"] = any(
                        str(t.get("reason") or "") == f"mutual_aid_offer:{offer_id}" and float(t.get("quantity_delta") or 0.0) < 0.0
                        for t in tx_rows_offering
                    )

                    requesting_state = str((row or {}).get("requesting_state") or "").zfill(2)
                    req_token = state_tokens.get(requesting_state)
                    if req_token:
                        tx_rows_requesting = list(get_json("/state/pool/transactions", token=req_token, params={"limit": 200}) or [])
                        mutual_aid_check["pool_tx_received_found"] = any(
                            str(t.get("reason") or "") == f"mutual_aid_receive:{offer_id}" and float(t.get("quantity_delta") or 0.0) > 0.0
                            for t in tx_rows_requesting
                        )

    report["mutual_aid_check"] = mutual_aid_check

    unique_districts = set(report["pagination_national"].get("unique_districts") or [])
    report["not_only_district_603"] = (len(unique_districts) > 1 and unique_districts != {"603"})

    report["finished_at"] = now_iso()
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "report_file": str(REPORT_PATH),
        "latest_live_run": report.get("latest_live_run"),
        "not_only_district_603": report.get("not_only_district_603"),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
