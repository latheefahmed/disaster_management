# Disaster Management Platform — UI Audit Handoff (Perplexity Agent)

## 1) Current Status (What is already done)

- Backend metadata endpoints are healthy:
  - `GET /metadata/states` returns state rows.
  - `GET /metadata/districts?state_code=33` returns district rows (including `603`).
- CORS issue was fixed in backend so frontend on non-5173 ports can fetch metadata dropdowns.
- Role logins were validated against backend auth endpoint.
- Existing automation artifacts:
  - Script: `backend/autonomous_ui_auditor.py`
  - Live helper: `backend/live_chromium_driver.py`
  - Report outputs: `backend/ui_audit_results.json`, `backend/UI_AUDIT_REPORT.md`
  - Screenshots: `backend/ui_screenshots/`
  - Videos: `backend/ui_videos/`

---

## 2) Environment + Ports

### Backend
- Base URL: `http://127.0.0.1:8000`
- Health check endpoints:
  - `GET /metadata/resources`
  - `GET /metadata/states`

### Frontend
- Active URL in this session: `http://localhost:5174`
- Login page: `http://localhost:5174/login`

### Important
- Frontend may move ports (`5173`, `5174`, `5175`) depending on conflicts.
- Always detect live port first, then run tests.

---

## 3) Credentials (verified)

### District (target)
- Username: `district_603`
- Password: `district123` ✅
- Password `disctrict123` ❌ invalid in this environment
- State code: `33`
- District code: `603`

### State (target)
- Username: `state_33`
- Password: `state123` ✅

### National
- Username: `national_admin`
- Password: `national123` ✅

### Admin
- Username: `admin`
- Password: `admin123` ✅

---

## 4) Login Navigation (exact)

On `/login`:
1. Fill username/password.
2. Select role dropdown (`district/state/national/admin`).
3. For district role:
   - Select state dropdown = `33`
   - Select district dropdown = `603`
4. For state role:
   - Select state dropdown = `33`
5. Click `Login`.
6. Verify route redirects to `/<role>`.

If dropdowns do not appear:
- Check browser console/network for CORS or failed metadata calls.
- Verify `GET /metadata/states` works from browser context (Origin = frontend URL).

---

## 5) Frontend Areas to Navigate (all dashboards)

## District (`/district` + `/district/request`)
- Main tabs:
  - `Requests`
  - `Allocations`
  - `Upstream Supply`
  - `Unmet`
  - `Agent Recommendations`
  - `Run History`
- Actions to test:
  - `Run Solver`
  - `Request Resources` / request form in `/district/request`
  - Claim/Consume/Return buttons in Allocations table

## State (`/state`)
- Tabs:
  - `District Requests`
  - `Mutual Aid Outgoing / Incoming`
  - `State Stock`
  - `Agent Recommendations`
  - `Run History`
- Validate district rollups for state `33` and district `603` presence

## National (`/national`)
- Tabs:
  - `State Summaries`
  - `National Stock`
  - `Inter-State Transfers`
  - `Agent Recommendations`
  - `Run History`

## Admin (`/admin`)
- Top tabs:
  - `System Health`
  - `Solver Runs`
  - `Neural Controller Status`
  - `Agent Findings`
  - `Audit Logs`
- Actions:
  - Create scenario
  - Add demand batch
  - Simulate scenario
  - Open run details/quick view
  - Approve recommendation (if pending)
  - Rerun scenario and verify run history changes

---

## 6) District Flow Test Matrix (must execute)

### Baseline KPI extraction (District 603)
Collect from UI cards:
- Total Final Demand
- Allocated Resources
- Unmet Demand
- Coverage %

Cross-check with backend:
- `/district/requests?latest_only=true`
- `/district/allocations`
- `/district/unmet`

### Case 1 — Small local demand
- Submit request: water-like resource, qty `10`
- Run solver
- Expect:
  - Request status allocated
  - Allocation exists
  - `supply_level = district`
  - `allocated_quantity > 0`

### Case 2 — Exceed district, use state
- Submit larger demand (iterative quantity if needed)
- Run solver
- Expect:
  - Allocation with `supply_level = state`
  - Shipment/receipt path visible
  - Receipt confirm transitions correctly

### Case 3 — Exceed state, use national
- Submit larger demand than case 2
- Run solver
- Expect `supply_level = national`

### Case 4 — Exceed all stock
- Submit very large demand
- Run solver
- Expect:
  - `allocated + unmet = final_demand`
  - Unmet visible in unmet tab

### Case 5 — Human-only resource
- Submit volunteers-like request qty `50`
- Expect:
  - `final_demand_quantity > 0`
  - Request not dropped
  - Allocation row exists

### Claim / Consume / Return cycle
- In Allocations tab:
  - Claim resource
  - Consume half
  - Return half
- Validate in backend:
  - `/district/claims`
  - `/district/consumptions`
  - `/district/returns`
- Validate stock/pool transaction side effects in state/national views

---

## 7) Invariants and Calculations (how metrics are computed)

## Core conservation invariant
For latest completed run:
- `allocated_total + unmet_total == final_demand_total`
- Tolerance threshold: `<= 0.0001`

Where:
- `final_demand_total = sum(final_demand_quantity from district requests latest_only)`
- `allocated_total = sum(allocated_quantity from district allocations)`
- `unmet_total = sum(unmet_quantity from district unmet rows)`

## Coverage
- `coverage_pct = (allocated_total / final_demand_total) * 100` when final demand > 0

## Data quality checks
- No duplicated allocation tuples for same run/slot/resource/origin key
- No stale `running` run when latest completed should drive UI
- No included request with zero final demand

---

## 8) Backend/API checklist (parallel validation)

For each major UI action, confirm API parity:
- Auth: `/auth/login`
- Metadata: `/metadata/states`, `/metadata/districts`, `/metadata/resources`
- District:
  - `/district/requests`
  - `/district/request-batch`
  - `/district/run`
  - `/district/solver-status`
  - `/district/allocations`
  - `/district/unmet`
  - `/district/claim`, `/district/consume`, `/district/return`
  - `/district/allocations/{id}/confirm`
- State:
  - `/state/allocations/summary`
  - `/state/pool`, `/state/pool/transactions`
  - `/state/mutual-aid/market`, `/state/mutual-aid/offers`
- National:
  - `/national/allocations/summary`
  - `/national/allocations/stock`
  - `/national/escalations`
- Admin:
  - `/admin/scenarios*`
  - `/admin/agent/recommendations`

---

## 9) Error classifications to emit

Use these categories in results:
- `UI_BUG`
- `BACKEND_BUG`
- `PERFORMANCE_ISSUE`
- `UX_REDUNDANCY`
- `DATA_MISMATCH`

And capture:
- Browser console errors
- 4xx/5xx responses
- request failures
- responses > 3 seconds

---

## 10) Report Generation (required artifacts)

## JSON
Write to: `backend/ui_audit_results.json`
Suggested shape:
```json
{
  "district_tests": {},
  "state_tests": {},
  "national_tests": {},
  "admin_tests": {},
  "invariant_violations": [],
  "ui_mismatches": [],
  "performance_issues": []
}
```

## Markdown
Write to: `backend/UI_AUDIT_REPORT.md`
Include:
- What works
- What fails
- Numerical evidence
- Screenshot/video paths
- Invariant breaks
- UX confusion/dead tabs/redundant controls
- Suggested fixes

---

## 11) Commands to run

### Start backend
```powershell
C:/Users/LATHEEF/Desktop/disaster_management/.venv/Scripts/python.exe C:/Users/LATHEEF/Desktop/disaster_management/backend/start_e2e_backend.py
```

### Start frontend
```powershell
cd C:/Users/LATHEEF/Desktop/disaster_management/frontend/disaster-frontend
npm run dev -- --host 127.0.0.1 --port 5173
```
(If 5173 busy, use the printed localhost port)

### Run full auditor
```powershell
$env:UI_AUDIT_FRONTEND_BASE='http://localhost:5174'
$env:UI_AUDIT_API_BASE='http://127.0.0.1:8000'
C:/Users/LATHEEF/Desktop/disaster_management/.venv/Scripts/python.exe C:/Users/LATHEEF/Desktop/disaster_management/backend/autonomous_ui_auditor.py
```

### Live manual/visual driver
```powershell
C:/Users/LATHEEF/Desktop/disaster_management/.venv/Scripts/python.exe C:/Users/LATHEEF/Desktop/disaster_management/backend/live_chromium_driver.py
```

---

## 12) Known issues observed so far

- District dashboard controls may intermittently not render quickly due to slow/aborted backend calls.
- Some high-latency endpoints (notably national summary) can exceed 3s and should be flagged.
- Browser console reports missing favicon 404 (low impact but appears as console error).

---

## 13) Practical strategy for Perplexity agent

1. Confirm live ports and login endpoint first.
2. Validate credentials via `/auth/login` before UI run.
3. Run role matrix login and screenshot each dashboard.
4. Execute district 5-case flow with fallback to API submit/run when UI stalls.
5. Perform claim/consume/return and verify via backend endpoints.
6. Traverse all state/national/admin tabs and cross-check data.
7. Run at least 2 passes for stability; compare differences.
8. Emit final JSON + Markdown report with all evidence links.

---

## 14) Stop note

All active custom auditor/driver runs have been paused for handoff. Use the commands above to resume under Perplexity agent control.
