# Disaster Management Platform — System Hardening Report

## 1) Root Causes Found

1. **Unmet ingest corruption**
   - `unmet_demand_u.csv` was written with headers, but loader read it as headerless (`header=None`), shifting columns and causing unmet rows to be invalid/empty.

2. **Ingest not transaction-safe**
   - Clear + insert for allocations were split across commits via service helpers, allowing partial/stale state if any insert failed.

3. **Action side-effects not reflected in allocation state**
   - Claim/consume/return wrote action rows but did not synchronize allocation slot status and quantities, so UI/DB drifted.

4. **Run-scoping gaps in action logs**
   - Claim/consumption/return tables were not scoped by `solver_run_id`, so aggregates could blend runs.

5. **Audit writes were out-of-transaction**
   - Audit logging used independent sessions, allowing audit trail divergence from action commits.

6. **Frontend stale state after POST**
   - District/admin screens relied on periodic polling and partial refreshes; post-action state was not immediately re-fetched with user-visible error surfacing.

7. **Admin simulation UX too flat**
   - No hierarchical country→state→district selection or batch controls for demand setup.

8. **Solver diagnostics insufficient**
   - No strict pre-run schema checks and no `run_summary.json` persisted with key dimensions/totals.

---

## 2) End-to-End Pipeline Truth Table

| Step | Path | Exists | Invocation | Commit/Persist | Visibility | Status |
|---|---|---|---|---|---|---|
| Frontend Action | district/admin UI actions | Yes | Yes | N/A | UI immediate | ✅ fixed |
| API Endpoint | routers (`district/state/national/admin`) | Yes | Yes | Service-driven | API response | ✅ fixed |
| Service Layer | request/scenario/action services | Yes | Yes | Yes | DB | ✅ fixed |
| DB Write | SQLAlchemy models/tables | Yes | Yes | Yes | Queryable | ✅ fixed |
| Solver Input Builder | scenario/live demand assembly | Yes | Yes | CSV persisted | Engine reads | ✅ fixed |
| Core Engine Run | `just_runs_cbc.py` | Yes | Yes | output CSV/json | bridge reads | ✅ fixed |
| CSV Outputs | allocation/unmet/summary | Yes | Yes | file write | parser reads | ✅ fixed |
| Ingest | engine bridge ingest | Yes | Yes | atomic clear+bulk insert | allocations table | ✅ fixed |
| DB Tables | allocations/claims/returns/audit | Yes | Yes | yes | frontend/API | ✅ fixed |
| Frontend Read | selectors/hooks | Yes | Yes | N/A | latest snapshot | ✅ fixed |

---

## 3) Endpoint Audit (Used in UI)

| Endpoint | Method | Purpose | Used in UI | Works |
|---|---|---|---|---|
| `/district/allocations` | GET | Latest live allocations for district | Yes | ✅ |
| `/district/unmet` | GET | Latest live unmet for district | Yes | ✅ |
| `/district/claim` | POST | Claim allocation | Yes | ✅ |
| `/district/consume` | POST | Consume claimed quantity | Yes | ✅ |
| `/district/return` | POST | Return remaining quantity | Yes | ✅ |
| `/district/claims` | GET | Claimed rows (normalized payload) | Yes | ✅ |
| `/district/consumptions` | GET | Consumption rows (normalized payload) | Yes | ✅ |
| `/district/returns` | GET | Return rows (normalized payload) | Yes | ✅ |
| `/district/demand-mode` | GET/PUT | Demand mode per district | Yes | ✅ |
| `/district/solver-status` | GET | Latest solver run status | Yes | ✅ |
| `/state/allocations` | GET | Latest live allocations per state | Yes | ✅ |
| `/state/unmet` | GET | Latest live unmet per state | Yes | ✅ |
| `/state/pool` | GET | State pool balance | Yes | ✅ |
| `/state/pool/allocate` | POST | Allocate from state pool | Yes | ✅ |
| `/national/allocations` | GET | Latest live national allocations | Yes | ✅ |
| `/national/unmet` | GET | Latest live national unmet | Yes | ✅ |
| `/national/pool` | GET | Global pool | Yes | ✅ |
| `/national/pool/allocate` | POST | National allocation from pool | Yes | ✅ |
| `/admin/scenarios` | GET/POST | Scenario list/create | Yes | ✅ |
| `/admin/scenarios/{id}/add-demand` | POST | Add scenario demand rows | Yes | ✅ |
| `/admin/scenarios/{id}/set-state-stock` | POST | Scenario state stock override | Yes | ✅ |
| `/admin/scenarios/{id}/set-national-stock` | POST | Scenario national stock override | Yes | ✅ |
| `/admin/scenarios/{id}/run` | POST | Execute scenario run | Yes | ✅ |
| `/admin/scenarios/{id}/runs` | GET | Run logs | Yes | ✅ |
| `/admin/scenarios/{id}/analysis` | GET | Explanations/recommendations | Yes | ✅ |

Dead/duplicate endpoint cleanup done:
- Removed duplicate route definitions in `state.py` for `/pool` and `/pool/allocate`.

---

## 4) Files Edited

### Backend
- `backend/app/engine_bridge/csv_loader.py`
- `backend/app/engine_bridge/ingest.py`
- `backend/app/services/allocation_service.py`
- `backend/app/services/action_service.py`
- `backend/app/services/audit_service.py`
- `backend/app/routers/district.py`
- `backend/app/routers/state.py`
- `backend/app/models/allocation.py`
- `backend/app/models/claim.py`
- `backend/app/models/consumption.py`
- `backend/app/models/return_.py`
- `backend/app/models/audit_log.py`
- `backend/app/database.py`
- `backend/app/schemas/allocation.py`
- `core_engine/phase4/optimization/loaders.py`
- `core_engine/phase4/optimization/build_model_cbc.py`
- `core_engine/phase4/optimization/just_runs_cbc.py`
- `backend/tests/test_system_hardening.py`

### Frontend
- `frontend/disaster-frontend/src/data/apiClient.ts` (new)
- `frontend/disaster-frontend/src/data/jsonLoader.ts`
- `frontend/disaster-frontend/src/state/districtClaims.ts`
- `frontend/disaster-frontend/src/state/districtConsumption.ts`
- `frontend/disaster-frontend/src/state/districtReturns.ts`
- `frontend/disaster-frontend/src/dashboards/district/DistrictOverview.tsx`
- `frontend/disaster-frontend/src/dashboards/admin/AdminOverview.tsx`

---

## 5) Verification Checklist

- [x] Re-run of scenario creates new `solver_runs` and ingests fresh allocations by run.
- [x] Ingest clears previous rows for same run and re-inserts atomically.
- [x] Unmet CSV parsing fixed (header-safe) and unmet rows persisted.
- [x] Claim updates allocation snapshot (`claimed_quantity`, `status`) in same transaction.
- [x] Return writes return row + pool transaction + allocation snapshot update in same transaction.
- [x] Demand mode (`human_only`, `baseline_only`, `baseline_plus_human`) enforced in demand assembly.
- [x] Solver writes `run_summary.json` with dimensions/totals.
- [x] Frontend refetches after district actions and surfaces user-visible errors.
- [x] Admin simulation includes hierarchical selector, multi-select, controls, and preview.
- [x] Regression tests added and passing.

---

## 6) Test Execution Results

- Backend tests:
  - `python -m unittest discover -s tests -p "test_*.py"`
  - Result: **OK (4 tests)**

- Frontend build:
  - `npm run build`
  - Result: **Success**
