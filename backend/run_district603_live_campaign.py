from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

BASE = "http://127.0.0.1:8000"
DISTRICT_USER = "district_603"
STATE_USER = "state_33"
NEIGHBOR_STATE_USER = "state_32"
NATIONAL_USER = "national_admin"

PASSWORD_CANDIDATES = {
    "district": ["district123", "pw", "password", "district_password"],
    "state": ["state123", "pw", "password", "state_password"],
    "national": ["national123", "pw", "password", "national_password"],
}

OUT_MD = Path("DISTRICT603_LIVE_CAMPAIGN_REPORT.md")
OUT_JSON = Path("DISTRICT603_LIVE_CAMPAIGN_REPORT.json")
OUT_PROGRESS = Path("DISTRICT603_LIVE_CAMPAIGN_PROGRESS.md")


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def login(username: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def login_with_candidates(usernames: list[str], passwords: list[str]) -> tuple[str, str, str]:
    errors: list[str] = []
    for username in usernames:
        for password in passwords:
            try:
                token = login(username, password)
                return username, password, token
            except requests.HTTPError as exc:
                errors.append(f"{username}/{password}: {exc}")
            except Exception as exc:
                errors.append(f"{username}/{password}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Unable to authenticate with candidates: " + "; ".join(errors[-6:]))


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_json(path: str, token: str, params: dict[str, Any] | None = None) -> Any:
    r = requests.get(f"{BASE}{path}", headers=headers(token), params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def post_json(path: str, token: str, payload: dict[str, Any], timeout_s: int = 40) -> tuple[int, Any]:
    r = requests.post(f"{BASE}{path}", headers=headers(token), json=payload, timeout=timeout_s)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    return r.status_code, body


def stock_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        rid = str(row.get("resource_id"))
        out[rid] = {
            "district_stock": float(row.get("district_stock") or 0.0),
            "state_stock": float(row.get("state_stock") or 0.0),
            "national_stock": float(row.get("national_stock") or 0.0),
            "in_transit": float(row.get("in_transit") or 0.0),
            "available_stock": float(row.get("available_stock") or 0.0),
        }
    return out


def case_quantity(allocated: float, idx: int) -> int:
    base = max(1, int(min(allocated, 12)))
    options = [1, 2, 3, 4, 5, 6, 7, 8]
    q = options[idx % len(options)]
    return max(1, min(base, q))


def to_md_table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    body = []
    for r in rows:
        body.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join([head, sep] + body)


def render_progress_bar(done: int, total: int, width: int = 24) -> str:
    total_safe = max(1, int(total))
    done_safe = max(0, min(int(done), total_safe))
    filled = int(round((done_safe / total_safe) * width))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def load_checkpoint() -> dict[str, Any] | None:
    if not OUT_JSON.exists():
        return None
    try:
        payload = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def save_checkpoint(meta: dict[str, Any], total_cases: int) -> None:
    done = len(meta.get("cases", []))
    bar = render_progress_bar(done, total_cases)
    progress_line = f"{done} completed {bar} ({done}/{total_cases})"

    meta.setdefault("progress", {})
    meta["progress"].update({
        "cases_completed": int(done),
        "cases_total": int(total_cases),
        "bar": bar,
        "line": progress_line,
        "updated_at": now_iso(),
    })

    OUT_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    OUT_PROGRESS.write_text(
        "\n".join([
            "# District 603 Live Campaign Progress",
            "",
            f"Updated: {meta['progress']['updated_at']}",
            "",
            f"- {progress_line}",
        ]) + "\n",
        encoding="utf-8",
    )
    print(progress_line)


def pick_cases(alloc_rows: list[dict[str, Any]], target: int = 25, min_resources: int = 10) -> list[dict[str, Any]]:
    usable = [
        r for r in alloc_rows
        if float(r.get("allocated_quantity") or 0.0) > 0
    ]
    usable.sort(key=lambda r: (-int(r.get("solver_run_id") or 0), int(r.get("time") or 0), int(r.get("id") or 0)))

    by_res: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in usable:
        by_res[str(row.get("resource_id"))].append(row)

    selected: list[dict[str, Any]] = []
    # first pass: ensure diversity by resource
    for rid in sorted(by_res.keys()):
        if len(selected) >= target:
            break
        if len(selected) < min_resources:
            selected.append(by_res[rid][0])

    # second pass: fill up to target from newest rows
    seen = {int(r.get("id") or 0) for r in selected}
    for row in usable:
        if len(selected) >= target:
            break
        if int(row.get("id") or 0) in seen:
            continue
        selected.append(row)
        seen.add(int(row.get("id") or 0))

    return selected[:target]


def wait_solver_completed(token: str, max_wait_s: int = 90) -> dict[str, Any]:
    started = time.time()
    last = {}
    while time.time() - started < max_wait_s:
        last = get_json("/district/solver-status", token)
        status = str(last.get("status") or "").lower()
        if status in {"completed", "failed", "failed_reconciliation"}:
            return last
        time.sleep(2)
    return last


def wait_run_id_completed(token: str, run_id: int, max_wait_s: int = 240) -> dict[str, Any]:
    started = time.time()
    last: dict[str, Any] = {}
    while time.time() - started < max_wait_s:
        rows = get_json("/district/run-history", token)
        if isinstance(rows, list):
            for row in rows:
                if int(row.get("run_id") or 0) == int(run_id):
                    last = row
                    status = str(row.get("status") or "").lower()
                    if status in {"completed", "failed", "failed_reconciliation"}:
                        return row
        time.sleep(2)
    return last


def main() -> None:
    checkpoint = load_checkpoint()

    meta: dict[str, Any] = {
        "started_at": now_iso(),
        "base_url": BASE,
        "cases": [],
        "escalation": {},
        "manual_aid": {},
    }

    if checkpoint and isinstance(checkpoint, dict):
        # resume only the case execution state; non-case sections will be refreshed at the end
        prior_cases = checkpoint.get("cases")
        if isinstance(prior_cases, list):
            meta["cases"] = prior_cases
        meta["started_at"] = str(checkpoint.get("started_at") or meta["started_at"])

    district_user, district_password, district_token = login_with_candidates(
        [DISTRICT_USER], PASSWORD_CANDIDATES["district"]
    )
    state_user, state_password, state_token = login_with_candidates(
        [STATE_USER], PASSWORD_CANDIDATES["state"]
    )
    neighbor_state_user, neighbor_state_password, neighbor_state_token = login_with_candidates(
        [NEIGHBOR_STATE_USER], PASSWORD_CANDIDATES["state"]
    )
    national_user, national_password, national_token = login_with_candidates(
        [NATIONAL_USER, "national_user"], PASSWORD_CANDIDATES["national"]
    )
    meta["auth"] = {
        "district": district_user,
        "state": state_user,
        "neighbor_state": neighbor_state_user,
        "national": national_user,
    }

    resources = get_json("/metadata/resources", district_token)
    resource_info = {str(r.get("resource_id")): r for r in resources}

    meta["seed_batch"] = {"status": "SKIP", "body": "Campaign uses existing real claimable completed allocations"}
    meta["seed_run"] = {"trigger_status": "SKIP", "trigger_body": "Not required", "solver_status": {}}

    pre_stock_rows = get_json("/district/stock", district_token)
    pre_stock = stock_map(pre_stock_rows)

    alloc_rows = get_json("/district/allocations", district_token)
    alloc_rows = [
        r for r in alloc_rows
        if str(r.get("status") or "").lower() == "allocated"
        and float(r.get("allocated_quantity") or 0.0) > 0
    ]

    cases = pick_cases(alloc_rows, target=25, min_resources=10)
    total_cases = len(cases)
    already_done = min(len(meta.get("cases", [])), total_cases)
    if already_done > 0:
        print(f"Resuming from checkpoint: {already_done} completed")
        save_checkpoint(meta, total_cases)

    for idx, row in enumerate(cases, start=1):
        if idx <= already_done:
            continue

        rid = str(row.get("resource_id"))
        t = int(row.get("time") or 0)
        run_id = int(row.get("solver_run_id") or 0)
        allocated = float(row.get("allocated_quantity") or 0.0)
        qty = case_quantity(allocated, idx)

        info = resource_info.get(rid, {})
        cls = str(info.get("class") or "").lower()
        is_consumable = cls == "consumable" or bool(info.get("is_consumable"))

        pre = pre_stock.get(rid, {"district_stock": 0.0, "state_stock": 0.0, "national_stock": 0.0, "available_stock": 0.0, "in_transit": 0.0})

        case = {
            "case_id": idx,
            "resource_id": rid,
            "resource_name": str(info.get("resource_name") or info.get("label") or rid),
            "class": cls or ("consumable" if is_consumable else "non_consumable"),
            "solver_run_id": run_id,
            "time": t,
            "allocated_qty": allocated,
            "attempt_qty": qty,
            "claim_status": None,
            "consume_status": None,
            "return_status": None,
            "pre_district": pre["district_stock"],
            "pre_state": pre["state_stock"],
            "pre_national": pre["national_stock"],
            "pre_available": pre["available_stock"],
        }

        c_status, c_body = post_json("/district/claim", district_token, {
            "resource_id": rid,
            "time": t,
            "quantity": qty,
            "claimed_by": "campaign",
            "solver_run_id": run_id,
        })
        case["claim_status"] = c_status
        case["claim_detail"] = c_body.get("detail") if isinstance(c_body, dict) else str(c_body)

        if c_status == 200:
            if is_consumable:
                s_status, s_body = post_json("/district/consume", district_token, {
                    "resource_id": rid,
                    "time": t,
                    "quantity": qty,
                    "solver_run_id": run_id,
                })
                case["consume_status"] = s_status
                case["consume_detail"] = s_body.get("detail") if isinstance(s_body, dict) else str(s_body)
                case["return_status"] = "N/A"
            else:
                src_scope = str(row.get("allocation_source_scope") or row.get("supply_level") or "")
                src_code = str(row.get("allocation_source_code") or row.get("origin_state_code") or row.get("state_code") or "")
                r_status, r_body = post_json("/district/return", district_token, {
                    "resource_id": rid,
                    "time": t,
                    "quantity": qty,
                    "reason": "manual",
                    "solver_run_id": run_id,
                    "allocation_source_scope": src_scope,
                    "allocation_source_code": src_code,
                })
                case["return_status"] = r_status
                case["return_detail"] = r_body.get("detail") if isinstance(r_body, dict) else str(r_body)
                case["consume_status"] = "N/A"
        else:
            case["consume_status"] = "SKIP"
            case["return_status"] = "SKIP"

        post_stock_rows = get_json("/district/stock", district_token)
        post_stock = stock_map(post_stock_rows)
        post = post_stock.get(rid, {"district_stock": 0.0, "state_stock": 0.0, "national_stock": 0.0, "available_stock": 0.0, "in_transit": 0.0})

        case["post_district"] = post["district_stock"]
        case["post_state"] = post["state_stock"]
        case["post_national"] = post["national_stock"]
        case["post_available"] = post["available_stock"]
        case["delta_district"] = round(post["district_stock"] - pre["district_stock"], 4)
        case["delta_state"] = round(post["state_stock"] - pre["state_stock"], 4)
        case["delta_national"] = round(post["national_stock"] - pre["national_stock"], 4)
        case["delta_available"] = round(post["available_stock"] - pre["available_stock"], 4)

        meta["cases"].append(case)
        save_checkpoint(meta, total_cases)

    # Escalation flow (one case)
    esc = {"requested": False, "solver_run": {}, "state_escalation": {}}
    e_status, e_body = post_json("/district/request", district_token, {
        "resource_id": "R37",
        "time": 0,
        "quantity": 14000,
        "priority": 5,
        "urgency": 5,
        "confidence": 1.0,
        "source": "human",
    })
    esc["requested"] = (e_status in {200, 201})
    esc["request_status"] = e_status
    esc["request_body"] = e_body

    try:
        run_status, run_body = post_json("/district/run", district_token, {}, timeout_s=300)
    except Exception as e:
        run_status, run_body = 599, {"detail": f"run trigger timeout/error: {e}"}
    esc["run_trigger_status"] = run_status
    esc["run_trigger_body"] = run_body
    esc["solver_run"] = wait_solver_completed(district_token)

    candidates = get_json("/state/escalations", state_token)
    esc["candidates_count"] = len(candidates) if isinstance(candidates, list) else 0
    if isinstance(candidates, list) and candidates:
        req_id = int(candidates[0].get("id"))
        s_status, s_body = post_json(f"/state/escalations/{req_id}", state_token, {"reason": "campaign_high_demand"})
        esc["state_escalation"] = {
            "request_id": req_id,
            "status": s_status,
            "body": s_body,
        }
    meta["escalation"] = esc

    # Manual aid flow (one case): district creates request, neighbor offers, state accepts
    aid = {"request": {}, "offer": {}, "accept": {}}
    m_status, m_body = post_json("/district/mutual-aid/request", district_token, {
        "resource_id": "R10",
        "quantity_requested": 9,
        "time": 0,
    })
    aid["request"] = {"status": m_status, "body": m_body}

    market = get_json("/state/mutual-aid/market", neighbor_state_token)
    chosen = None
    if isinstance(market, list):
        for row in market:
            if str(row.get("requesting_state")) == "33":
                chosen = row
                break

    if chosen:
        offer_status, offer_body = post_json("/state/mutual-aid/offers", neighbor_state_token, {
            "request_id": int(chosen.get("id")),
            "quantity_offered": 5,
        })
        aid["offer"] = {"status": offer_status, "body": offer_body}
        if offer_status == 200:
            offer_id = int(offer_body.get("offer_id"))
            accept_status, accept_body = post_json(f"/state/mutual-aid/offers/{offer_id}/respond", state_token, {
                "decision": "accepted",
            })
            aid["accept"] = {"status": accept_status, "body": accept_body}
    else:
        aid["offer"] = {"status": "SKIP", "body": "No market request visible for requesting_state=33"}

    meta["manual_aid"] = aid

    post_stock_rows = get_json("/district/stock", district_token)
    post_stock = stock_map(post_stock_rows)

    # summary stats
    success_claims = sum(1 for c in meta["cases"] if c.get("claim_status") == 200)
    success_consumes = sum(1 for c in meta["cases"] if c.get("consume_status") == 200)
    success_returns = sum(1 for c in meta["cases"] if c.get("return_status") == 200)
    distinct_resources = len({c["resource_id"] for c in meta["cases"]})

    meta["summary"] = {
        "ended_at": now_iso(),
        "cases_total": len(meta["cases"]),
        "resources_covered": distinct_resources,
        "claims_ok": success_claims,
        "consumes_ok": success_consumes,
        "returns_ok": success_returns,
    }
    save_checkpoint(meta, total_cases)

    # Build markdown report
    cols = [
        "case_id", "resource_id", "resource_name", "class", "solver_run_id", "time",
        "allocated_qty", "attempt_qty", "claim_status", "consume_status", "return_status",
        "pre_district", "post_district", "delta_district",
        "pre_state", "post_state", "delta_state",
        "pre_national", "post_national", "delta_national",
        "pre_available", "post_available", "delta_available",
    ]

    md = []
    md.append("# District 603 Live Campaign Report")
    md.append("")
    md.append(f"- Generated at: {meta['summary']['ended_at']}")
    md.append(f"- Cases executed: {meta['summary']['cases_total']}")
    md.append(f"- Distinct resources: {meta['summary']['resources_covered']}")
    md.append(f"- Claim OK: {meta['summary']['claims_ok']}, Consume OK: {meta['summary']['consumes_ok']}, Return OK: {meta['summary']['returns_ok']}")
    md.append("")

    md.append("## Action Cases (Pre/Post)")
    md.append("")
    md.append(to_md_table(meta["cases"], cols))
    md.append("")

    md.append("## Escalation Flow")
    md.append("")
    md.append("```json")
    md.append(json.dumps(meta["escalation"], indent=2, default=str))
    md.append("```")
    md.append("")

    md.append("## Manual Aid Flow")
    md.append("")
    md.append("```json")
    md.append(json.dumps(meta["manual_aid"], indent=2, default=str))
    md.append("```")
    md.append("")

    md.append("## Stock Snapshot Delta by Resource")
    delta_rows = []
    for rid, pre in sorted(pre_stock.items()):
        post = post_stock.get(rid, {"district_stock": 0.0, "state_stock": 0.0, "national_stock": 0.0, "available_stock": 0.0, "in_transit": 0.0})
        delta_rows.append({
            "resource_id": rid,
            "pre_district": round(pre["district_stock"], 4),
            "post_district": round(post["district_stock"], 4),
            "delta_district": round(post["district_stock"] - pre["district_stock"], 4),
            "pre_state": round(pre["state_stock"], 4),
            "post_state": round(post["state_stock"], 4),
            "delta_state": round(post["state_stock"] - pre["state_stock"], 4),
            "pre_national": round(pre["national_stock"], 4),
            "post_national": round(post["national_stock"], 4),
            "delta_national": round(post["national_stock"] - pre["national_stock"], 4),
            "pre_available": round(pre["available_stock"], 4),
            "post_available": round(post["available_stock"], 4),
            "delta_available": round(post["available_stock"] - pre["available_stock"], 4),
        })

    md.append("")
    md.append(to_md_table(delta_rows, [
        "resource_id", "pre_district", "post_district", "delta_district",
        "pre_state", "post_state", "delta_state",
        "pre_national", "post_national", "delta_national",
        "pre_available", "post_available", "delta_available",
    ]))

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    OUT_JSON.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    print(json.dumps(meta["summary"], indent=2))
    print(f"report_md={OUT_MD}")
    print(f"report_json={OUT_JSON}")


if __name__ == "__main__":
    main()
