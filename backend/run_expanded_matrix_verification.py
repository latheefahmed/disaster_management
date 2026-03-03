import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func

from app.main import app
from app.database import SessionLocal
from app.models.allocation import Allocation
from app.models.district import District
from app.models.pool_transaction import PoolTransaction
from app.models.resource import Resource
from app.models.solver_run import SolverRun
from app.models.user import User
from app.services.resource_policy import is_resource_consumable, is_resource_returnable
from app.utils.hashing import hash_password
from e2e_seed_data import seed_e2e_data


def _upsert_user(db, username: str, password: str, role: str, state_code: str | None, district_code: str | None):
    row = db.query(User).filter(User.username == username).first()
    if row is None:
        row = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            state_code=state_code,
            district_code=district_code,
            is_active=True,
        )
        db.add(row)
    else:
        row.password_hash = hash_password(password)
        row.role = role
        row.state_code = state_code
        row.district_code = district_code
        row.is_active = True


def _login(client: TestClient, username: str, password: str = "pw") -> str:
    res = client.post("/auth/login", json={"username": username, "password": password})
    if res.status_code != 200:
        raise RuntimeError(f"Login failed for {username}: {res.status_code} {res.text}")
    return str(res.json()["access_token"])


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _call_json(client: TestClient, method: str, path: str, headers: dict | None = None, payload: dict | None = None):
    if method == "GET":
        res = client.get(path, headers=headers)
    elif method == "POST":
        res = client.post(path, headers=headers, json=payload or {})
    elif method == "PUT":
        res = client.put(path, headers=headers, json=payload or {})
    else:
        raise ValueError(f"Unsupported method {method}")

    body = None
    try:
        body = res.json()
    except Exception:
        body = {"raw": res.text}
    return res.status_code, body


def _append_report(summary: dict):
    report_path = Path("SYSTEM_VERIFICATION_REPORT.md")
    if not report_path.exists():
        return

    section = [
        "",
        "## Expanded Matrix Verification",
        f"Generated: `{summary['generated_at']}`",
        "",
        "### Coverage",
        f"- districts covered: `{summary['coverage']['district_count']}`",
        f"- states covered: `{summary['coverage']['state_count']}`",
        f"- resources checked: `{summary['coverage']['resource_count']}`",
        f"- scenario demand rows inserted: `{summary['coverage']['scenario_rows_inserted']}`",
        "",
        "### Role + Button Flow Results",
        f"- district endpoints pass/total: `{summary['checks']['district_endpoint_pass']}/{summary['checks']['district_endpoint_total']}`",
        f"- district action pass/total: `{summary['checks']['district_action_pass']}/{summary['checks']['district_action_total']}`",
        f"- state action pass/total: `{summary['checks']['state_action_pass']}/{summary['checks']['state_action_total']}`",
        f"- national action pass/total: `{summary['checks']['national_action_pass']}/{summary['checks']['national_action_total']}`",
        f"- mutual aid flow pass/total: `{summary['checks']['mutual_aid_pass']}/{summary['checks']['mutual_aid_total']}`",
        f"- frontend wiring checks pass/total: `{summary['checks']['frontend_wiring_pass']}/{summary['checks']['frontend_wiring_total']}`",
        "",
        "### Notes",
        f"- returnable resource used for pool actions: `{summary['selected']['returnable_resource']}`",
        f"- consumable resource used for consume action: `{summary['selected']['consumable_resource']}`",
    ]

    report_path.write_text(report_path.read_text(encoding="utf-8") + "\n".join(section) + "\n", encoding="utf-8")


def main():
    seed_e2e_data()
    db = SessionLocal()

    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "coverage": {},
        "selected": {},
        "checks": {
            "district_endpoint_pass": 0,
            "district_endpoint_total": 0,
            "district_action_pass": 0,
            "district_action_total": 0,
            "state_action_pass": 0,
            "state_action_total": 0,
            "national_action_pass": 0,
            "national_action_total": 0,
            "mutual_aid_pass": 0,
            "mutual_aid_total": 0,
            "frontend_wiring_pass": 0,
            "frontend_wiring_total": 0,
        },
        "details": {
            "district_users": [],
            "state_users": [],
            "district_checks": [],
            "district_actions": [],
            "state_actions": [],
            "national_actions": [],
            "mutual_aid": [],
            "frontend_wiring": [],
        },
    }

    try:
        state_codes = [
            str(r[0])
            for r in db.query(District.state_code)
            .filter(District.state_code.isnot(None))
            .group_by(District.state_code)
            .order_by(District.state_code.asc())
            .all()
        ]
        selected_states = state_codes[:3]
        if len(selected_states) < 2:
            raise RuntimeError("Need at least 2 states in DB for expanded verification")

        selected_districts = []
        for st in selected_states:
            rows = (
                db.query(District)
                .filter(District.state_code == st)
                .order_by(District.district_code.asc())
                .limit(4)
                .all()
            )
            selected_districts.extend(rows)
        selected_districts = selected_districts[:7]
        if len(selected_districts) < 7:
            raise RuntimeError("Need at least 7 districts for expanded verification")

        resources = [str(r.resource_id) for r in db.query(Resource).order_by(Resource.resource_id.asc()).all()]
        if not resources:
            raise RuntimeError("No resources found")

        returnable = next((r for r in resources if is_resource_returnable(r)), None)
        consumable = next((r for r in resources if is_resource_consumable(r)), None)
        if returnable is None or consumable is None:
            raise RuntimeError("Need both returnable and consumable resources")

        result["selected"] = {
            "states": selected_states,
            "districts": [str(d.district_code) for d in selected_districts],
            "returnable_resource": returnable,
            "consumable_resource": consumable,
        }

        for d in selected_districts:
            uname = f"verify_d_{d.district_code}"
            _upsert_user(db, uname, "pw", "district", str(d.state_code), str(d.district_code))
            result["details"]["district_users"].append(uname)

        for st in selected_states:
            uname = f"verify_s_{st}"
            _upsert_user(db, uname, "pw", "state", st, None)
            result["details"]["state_users"].append(uname)

        _upsert_user(db, "verify_admin", "pw", "admin", None, None)
        _upsert_user(db, "verify_national", "pw", "national", None, None)

        run = SolverRun(mode="live", status="completed")
        db.add(run)
        db.flush()

        for idx, d in enumerate(selected_districts):
            for rid in resources:
                qty = float(6 + (idx % 3))
                db.add(
                    Allocation(
                        solver_run_id=int(run.id),
                        request_id=0,
                        supply_level="district",
                        resource_id=str(rid),
                        district_code=str(d.district_code),
                        state_code=str(d.state_code),
                        origin_state=str(d.state_code),
                        origin_state_code=str(d.state_code),
                        origin_district_code=str(d.district_code),
                        time=0,
                        allocated_quantity=qty,
                        is_unmet=False,
                        claimed_quantity=0.0,
                        consumed_quantity=0.0,
                        returned_quantity=0.0,
                        status="allocated",
                    )
                )

        first_d = selected_districts[0]
        db.add(
            Allocation(
                solver_run_id=int(run.id),
                request_id=0,
                supply_level="state",
                resource_id=returnable,
                district_code=str(first_d.district_code),
                state_code=str(first_d.state_code),
                origin_state=str(first_d.state_code),
                origin_state_code=str(first_d.state_code),
                origin_district_code=None,
                time=0,
                allocated_quantity=5.0,
                is_unmet=False,
                claimed_quantity=0.0,
                consumed_quantity=0.0,
                returned_quantity=0.0,
                status="allocated",
            )
        )
        db.add(
            Allocation(
                solver_run_id=int(run.id),
                request_id=0,
                supply_level="national",
                resource_id=returnable,
                district_code=str(first_d.district_code),
                state_code=str(first_d.state_code),
                origin_state="NATIONAL",
                origin_state_code="NATIONAL",
                origin_district_code=None,
                time=0,
                allocated_quantity=4.0,
                is_unmet=False,
                claimed_quantity=0.0,
                consumed_quantity=0.0,
                returned_quantity=0.0,
                status="allocated",
            )
        )
        db.commit()

        result["coverage"] = {
            "district_count": len(selected_districts),
            "state_count": len({str(d.state_code) for d in selected_districts}),
            "resource_count": len(resources),
            "synthetic_run_id": int(run.id),
        }

        client = TestClient(app)
        district_tokens = {u: _login(client, u, "pw") for u in result["details"]["district_users"]}
        state_tokens = {u: _login(client, u, "pw") for u in result["details"]["state_users"]}
        admin_token = _login(client, "verify_admin", "pw")
        national_token = _login(client, "verify_national", "pw")

        district_paths = [
            "/district/me",
            "/district/allocations",
            "/district/unmet",
            "/district/solver-status",
            "/district/requests",
        ]
        for user, token in district_tokens.items():
            for path in district_paths:
                code, body = _call_json(client, "GET", path, headers=_auth(token))
                ok = code == 200
                result["checks"]["district_endpoint_total"] += 1
                if ok:
                    result["checks"]["district_endpoint_pass"] += 1
                result["details"]["district_checks"].append({"user": user, "path": path, "status": code, "ok": ok, "body": body})

        latest_live = (
            db.query(SolverRun)
            .filter(SolverRun.mode == "live", SolverRun.status == "completed")
            .order_by(SolverRun.id.desc())
            .first()
        )
        if latest_live is None:
            raise RuntimeError("No completed live run available for district action checks")

        slot_rows = (
            db.query(
                Allocation.district_code,
                Allocation.state_code,
                Allocation.resource_id,
                Allocation.time,
                func.coalesce(func.sum(Allocation.allocated_quantity), 0.0).label("qty"),
            )
            .filter(
                Allocation.solver_run_id == int(latest_live.id),
                Allocation.is_unmet == False,
            )
            .group_by(
                Allocation.district_code,
                Allocation.state_code,
                Allocation.resource_id,
                Allocation.time,
            )
            .all()
        )

        consumable_slot = None
        returnable_slot = None
        for row in slot_rows:
            qty = float(row.qty or 0.0)
            if qty < 1.0:
                continue
            if consumable_slot is None and is_resource_consumable(str(row.resource_id)):
                consumable_slot = row
            if returnable_slot is None and is_resource_returnable(str(row.resource_id)):
                returnable_slot = row
            if consumable_slot is not None and returnable_slot is not None:
                break

        if consumable_slot is None or returnable_slot is None:
            raise RuntimeError("Unable to find consumable and returnable slots in latest completed live run")

        for slot in [consumable_slot, returnable_slot]:
            username = f"verify_d_{slot.district_code}"
            if username not in district_tokens:
                _upsert_user(db, username, "pw", "district", str(slot.state_code), str(slot.district_code))
                db.commit()
                district_tokens[username] = _login(client, username, "pw")

        consumable_user = f"verify_d_{consumable_slot.district_code}"
        returnable_user = f"verify_d_{returnable_slot.district_code}"

        district_actions = [
            (
                "claim_consumable",
                consumable_user,
                "POST",
                "/district/claim",
                {
                    "resource_id": str(consumable_slot.resource_id),
                    "time": int(consumable_slot.time),
                    "quantity": 1,
                    "claimed_by": "verify",
                },
            ),
            (
                "consume_consumable",
                consumable_user,
                "POST",
                "/district/consume",
                {
                    "resource_id": str(consumable_slot.resource_id),
                    "time": int(consumable_slot.time),
                    "quantity": 1,
                },
            ),
            (
                "claim_returnable",
                returnable_user,
                "POST",
                "/district/claim",
                {
                    "resource_id": str(returnable_slot.resource_id),
                    "time": int(returnable_slot.time),
                    "quantity": 1,
                    "claimed_by": "verify",
                },
            ),
            (
                "return_returnable",
                returnable_user,
                "POST",
                "/district/return",
                {
                    "resource_id": str(returnable_slot.resource_id),
                    "time": int(returnable_slot.time),
                    "quantity": 1,
                    "reason": "manual",
                },
            ),
            ("list_claims", returnable_user, "GET", "/district/claims", None),
            ("list_consumptions", consumable_user, "GET", "/district/consumptions", None),
            ("list_returns", returnable_user, "GET", "/district/returns", None),
        ]
        for name, action_user, method, path, payload in district_actions:
            code, body = _call_json(client, method, path, headers=_auth(district_tokens[action_user]), payload=payload)
            ok = code == 200
            result["checks"]["district_action_total"] += 1
            if ok:
                result["checks"]["district_action_pass"] += 1
            result["details"]["district_actions"].append({"name": name, "user": action_user, "status": code, "ok": ok, "body": body})

        first_state = str(selected_districts[0].state_code)
        state_user = f"verify_s_{first_state}"
        state_token = state_tokens[state_user]
        state_actions = [
            ("state_pool_before", "GET", "/state/pool", None),
            ("state_pool_allocate", "POST", "/state/pool/allocate", {"resource_id": returnable, "time": 0, "quantity": 1, "target_district": str(selected_districts[0].district_code), "note": "verify"}),
            ("state_pool_after", "GET", "/state/pool", None),
            ("state_pool_transactions", "GET", "/state/pool/transactions", None),
        ]
        for name, method, path, payload in state_actions:
            code, body = _call_json(client, method, path, headers=_auth(state_token), payload=payload)
            ok = code == 200
            result["checks"]["state_action_total"] += 1
            if ok:
                result["checks"]["state_action_pass"] += 1
            result["details"]["state_actions"].append({"name": name, "status": code, "ok": ok, "body": body})

        national_actions = [
            ("national_pool", "GET", "/national/pool", None),
            ("national_pool_allocate", "POST", "/national/pool/allocate", {"state_code": first_state, "resource_id": returnable, "time": 0, "quantity": 1, "target_district": str(selected_districts[0].district_code), "note": "verify"}),
            ("national_pool_transactions", "GET", "/national/pool/transactions", None),
        ]
        for name, method, path, payload in national_actions:
            code, body = _call_json(client, method, path, headers=_auth(national_token), payload=payload)
            ok = code == 200
            result["checks"]["national_action_total"] += 1
            if ok:
                result["checks"]["national_action_pass"] += 1
            result["details"]["national_actions"].append({"name": name, "status": code, "ok": ok, "body": body})

        if len(selected_states) >= 2:
            request_state = selected_states[1]
            req_district = next(d for d in selected_districts if str(d.state_code) == request_state)
            req_user = f"verify_d_{req_district.district_code}"
            req_token = district_tokens[req_user]

            code_req, body_req = _call_json(
                client,
                "POST",
                "/district/mutual-aid/request",
                headers=_auth(req_token),
                payload={"resource_id": returnable, "quantity_requested": 2, "time": 0},
            )
            ok_req = code_req == 200
            result["checks"]["mutual_aid_total"] += 1
            if ok_req:
                result["checks"]["mutual_aid_pass"] += 1
            result["details"]["mutual_aid"].append({"name": "create_request", "status": code_req, "ok": ok_req, "body": body_req})

            code_market, body_market = _call_json(client, "GET", "/state/mutual-aid/market", headers=_auth(state_token))
            ok_market = code_market == 200
            result["checks"]["mutual_aid_total"] += 1
            if ok_market:
                result["checks"]["mutual_aid_pass"] += 1
            result["details"]["mutual_aid"].append({"name": "market", "status": code_market, "ok": ok_market, "body": body_market})

            offer_id = None
            if isinstance(body_market, list):
                request_id = int(body_req.get("request_id")) if isinstance(body_req, dict) and body_req.get("request_id") else None
                for row in body_market:
                    if request_id is not None and int(row.get("request_id", -1)) == request_id:
                        code_offer, body_offer = _call_json(
                            client,
                            "POST",
                            "/state/mutual-aid/offers",
                            headers=_auth(state_token),
                            payload={"request_id": request_id, "quantity_offered": 1},
                        )
                        ok_offer = code_offer == 200
                        result["checks"]["mutual_aid_total"] += 1
                        if ok_offer:
                            result["checks"]["mutual_aid_pass"] += 1
                        result["details"]["mutual_aid"].append({"name": "offer", "status": code_offer, "ok": ok_offer, "body": body_offer})
                        if ok_offer and isinstance(body_offer, dict) and body_offer.get("offer_id"):
                            offer_id = int(body_offer["offer_id"])
                        break

            if offer_id is not None:
                req_state_token = state_tokens.get(f"verify_s_{request_state}")
                if req_state_token is not None:
                    code_resp, body_resp = _call_json(
                        client,
                        "POST",
                        f"/state/mutual-aid/offers/{offer_id}/respond",
                        headers=_auth(req_state_token),
                        payload={"decision": "accept"},
                    )
                    ok_resp = code_resp == 200
                    result["checks"]["mutual_aid_total"] += 1
                    if ok_resp:
                        result["checks"]["mutual_aid_pass"] += 1
                    result["details"]["mutual_aid"].append({"name": "respond", "status": code_resp, "ok": ok_resp, "body": body_resp})

        code_sc, body_sc = _call_json(client, "POST", "/admin/scenarios", headers=_auth(admin_token), payload={"name": "EXPANDED_MATRIX_E2E"})
        scenario_rows = 0
        if code_sc == 200 and isinstance(body_sc, dict) and body_sc.get("id") is not None:
            sid = int(body_sc["id"])
            rows = []
            for d in selected_districts:
                for rid in resources:
                    rows.append({
                        "district_code": str(d.district_code),
                        "state_code": str(d.state_code),
                        "resource_id": rid,
                        "time": 0,
                        "quantity": 2.0,
                    })
            scenario_rows = len(rows)
            code_add, body_add = _call_json(
                client,
                "POST",
                f"/admin/scenarios/{sid}/add-demand-batch",
                headers=_auth(admin_token),
                payload={"rows": rows},
            )
            result["details"]["state_actions"].append({"name": "admin_scenario_add_batch", "status": code_add, "ok": code_add == 200, "body": body_add})

        result["coverage"]["scenario_rows_inserted"] = scenario_rows

        frontend_checks = [
            (
                "backend_paths_actions",
                Path("..") / "frontend" / "disaster-frontend" / "src" / "data" / "backendPaths.ts",
                [
                    "districtClaim",
                    "districtConsume",
                    "districtReturn",
                    "districtConfirmAllocationReceipt",
                    "statePoolAllocate",
                    "nationalPoolAllocate",
                    "districtMutualAidRequest",
                    "stateMutualAidOffers",
                    "stateMutualAidOfferRespond",
                ],
            ),
            (
                "district_overview_tabs",
                Path("..") / "frontend" / "disaster-frontend" / "src" / "dashboards" / "district" / "DistrictOverview.tsx",
                ["Upstream Supply"],
            ),
            (
                "state_overview_tabs",
                Path("..") / "frontend" / "disaster-frontend" / "src" / "dashboards" / "state" / "StateOverview.tsx",
                ["Mutual Aid Outgoing / Incoming"],
            ),
            (
                "national_overview_tabs",
                Path("..") / "frontend" / "disaster-frontend" / "src" / "dashboards" / "national" / "NationalOverview.tsx",
                ["Inter-State Transfers"],
            ),
        ]

        for name, path, needles in frontend_checks:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            ok = bool(text) and all(n in text for n in needles)
            result["checks"]["frontend_wiring_total"] += 1
            if ok:
                result["checks"]["frontend_wiring_pass"] += 1
            result["details"]["frontend_wiring"].append({"name": name, "path": str(path), "ok": ok, "needles": needles})

        pool_count = int(db.query(func.count(PoolTransaction.id)).scalar() or 0)
        alloc_count = int(db.query(func.count(Allocation.id)).filter(Allocation.solver_run_id == int(run.id)).scalar() or 0)
        result["coverage"]["synthetic_allocations_for_run"] = alloc_count
        result["coverage"]["total_pool_transactions_after_checks"] = pool_count

    finally:
        db.close()

    out_path = Path("expanded_matrix_verification.json")
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    _append_report(result)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
