# FINAL VALIDATION REPORT

## Scope
End-to-end allocation correctness was revalidated across solver output, ingest pipeline, backend query surfaces, and frontend consumers.

## Root-Cause Bugs Fixed

### Bug 1 — Unconstrained state/national allocation when stock key missing
- Root cause: legacy CBC constraints skipped stock constraints when lookup key was absent, leaving flows unconstrained.
- File & line:
  - `core_engine/phase4/optimization/model_constraints.py:86`
  - `core_engine/phase4/optimization/model_constraints.py:101`
- Fix applied:
  - Missing stock caps now default to `0.0` and constraints are always emitted.
- Before result:
  - Canonical run produced unrealistic row: `state ... allocated_quantity=999995.0` with stock override not matching solver state.
- After result:
  - Canonical matrix passes with physically bounded flows; see `core_engine/phase4/scenarios/generated/validation_matrix/solver_validation_summary.json`.

### Bug 2 — Demand/stock unit mismatch (100000x demand scaling)
- Root cause: demand values were scaled by `100_000`, while stock and requests were not, causing systemic unmet/over-allocation distortions.
- File & line:
  - `core_engine/phase4/optimization/loaders.py:9`
  - `backend/app/services/final_demand_service.py:10`
- Fix applied:
  - Set `DEMAND_UNIT_MULTIPLIER = 1` in both solver-side and final-demand persistence.
- Before result:
  - Canonical demand `10` became `1,000,000` in solver artifacts.
- After result:
  - Canonical demand remains `10`; allocation and unmet are numerically consistent.

### Bug 3 — State code drift between solver geography map and backend district master
- Root cause: ingest trusted solver `state_code` directly; backend dashboards filter by backend district `state_code`.
- File & line:
  - `backend/app/engine_bridge/ingest.py:99`
- Fix applied:
  - Ingest now derives destination `state_code` from backend district master map (`districts` table) when available.
- Before result:
  - State dashboard could miss valid allocation rows due to state-code mismatch.
- After result:
  - Allocation rows are aligned to backend district ownership and visible to role-scoped queries.

### Bug 4 — Missing supply-level persistence to API/UI contracts
- Root cause: `allocations` table/schema did not persist `supply_level`, while frontend contracts expect it.
- File & line:
  - `backend/app/models/allocation.py:14`
  - `backend/app/schemas/allocation.py:10`
  - `backend/app/database.py:65`
  - `backend/app/engine_bridge/ingest.py:117`
- Fix applied:
  - Added `supply_level` to ORM model, runtime migration, API schema, and ingest mapping.
  - Unmet rows tagged as `supply_level="unmet"` in ingestion records.
- After result:
  - Frontend receives explicit source-level provenance in allocation payloads.

## Mandatory Workflow Evidence

### A) Solver output verification
- Artifact: `core_engine/phase4/scenarios/generated/validation_matrix/solver_validation_summary.json`
- Result: all canonical scenarios pass (`all_passed=true`).
- Sample rows:
  - `core_engine/phase4/scenarios/generated/validation_matrix/district_then_state_allocation_x.csv`
    - `district,R1,1,1,1,5.0`
    - `state,R1,1,1,1,5.0`
  - `core_engine/phase4/scenarios/generated/validation_matrix/district_then_state_unmet_demand_u.csv`
    - no unmet rows

### B) Backend ingest verification
- Artifact: `core_engine/phase4/scenarios/generated/validation_matrix/ingest_parity_snapshot.json`
- SQL-equivalent snapshot:
  - CSV alloc count/sum: `2 / 10.0`
  - DB alloc count/sum: `2 / 10.0`
  - CSV unmet count/sum: `0 / 0.0`
  - DB unmet count/sum: `0 / 0.0`
  - `all_match=true`

### C) Merge logic verification
- Artifact: `core_engine/phase4/scenarios/generated/validation_matrix/pipeline_semantics_snapshot.json`
- Result:
  - merged rows: `2`
  - merged total demand: `45.0`
  - nonzero demand retained: `true`

### D) Stock table verification
- Verified positive stock in source data:
  - `core_engine/phase4/resources/synthetic_data/district_resource_stock.csv`
  - `core_engine/phase4/resources/synthetic_data/state_resource_stock.csv`
  - `core_engine/phase4/resources/synthetic_data/national_resource_stock.csv`

### E) Frontend data fetch verification
- Backend path routing uses API endpoints, not CSV reads:
  - `frontend/disaster-frontend/src/data/backendPaths.ts`
- District/state/national dashboards consume backend allocation/unmet endpoints and summaries.

## Canonical Test Scenario Results

### Scenario 1: district sufficient
- Input: district stock `100`, request `10`.
- Result: district allocation `10`, unmet `0`.
- End-to-end artifact: `core_engine/phase4/scenarios/generated/validation_matrix/canonical_e2e_snapshot.json` (`passes=true`).

### Scenario 2: district + state
- Input: district stock `5`, state stock `100`, request `10`.
- Result: district `5`, state `5`, unmet `0`.
- Evidence: `district_then_state_allocation_x.csv`.

### Scenario 3: district + national
- Input: district stock `5`, state stock `0`, national stock `100`, request `10`.
- Result: district `5`, national `5`, unmet `0`.
- Evidence: `solver_validation_summary.json`.

## Escalation Semantics Validation
- Escalation updates request status only; no direct allocation side effect.
- Artifact: `core_engine/phase4/scenarios/generated/validation_matrix/pipeline_semantics_snapshot.json`
  - `allocation_count_before == allocation_count_after`
  - `direct_allocation_side_effect=false`

## Transport & Receipt Validation
- Receipt confirmation path verified:
  - `receipt_confirmed=true`
  - `receipt_time_present=true`
- Artifact: `pipeline_semantics_snapshot.json`

## Regression & UI Validation Matrix

### Backend tests executed
- `tests/test_system_hardening.py` — pass
- `tests/test_phase6_hardening.py` — pass
- `tests/test_phase7_end_to_end_contract.py` — pass
- `tests/test_phase8_solver_multiperiod.py` — pass
- `tests/test_phase10_neural_scaffold.py` — pass
- `tests/test_api_endpoints_full.py` — pass

### Frontend tests executed
- `src/__tests__/districtOverview.test.tsx` — pass
- `src/__tests__/dashboardQualitySignals.test.tsx` — pass

## Invariant Check
- Solver still authoritative (CBC/PuLP).
- No manual allocation table overrides were introduced.
- No fake allocations were added.
- Errors are surfaced (no silent swallowing added in fixed paths).

## Success Criteria Outcome
- Canonical scenario: ✅
- Multi-level allocation scenario: ✅
- Escalation semantics (future-run signal only): ✅
- Frontend reflects backend APIs: ✅ (contract + render tests)
- No negative/NaN in validation scenarios: ✅
- `allocated + unmet = demand`: ✅ (solver + ingest parity + canonical E2E)

## Remaining Known Limitations
1. Legacy single-step solver path (`horizon <= 1`) is still used by design; Phase 8 rolling path remains separate.
2. Existing codebase has deprecation warnings (`datetime.utcnow`, Pydantic v2 config) not in scope of this correctness fix.
3. State dashboard does not have row-click drilldown navigation; district-level detail is surfaced via the explicit toggle (`Show District-Level Details`).

## Max-Cycle Lifecycle & Cross-Level Visibility Extension

### Lifecycle parity artifact (district ↔ state)
- New executable audit: `backend/run_lifecycle_visibility_check.py`
- Artifact: `core_engine/phase4/scenarios/generated/validation_matrix/lifecycle_visibility_snapshot.json`
- Verified request status parity for the same probe requests across:
  - district surface (`/district/requests`)
  - state surface (`/state/requests`)
- Expected and observed statuses match 1:1:
  - `pending`
  - `allocated`
  - `partial`
  - `unmet`
  - `escalated_national`

### Allocation slot lifecycle proof
- Verified slot status transition chain (same district/resource/time slot):
  - `allocated -> claimed -> partially_returned -> closed`
- This is enforced via backend claim/return actions (no manual DB status override).

### State-level district consistency proof
- For the probed district slot, parity check passed:
  - district slot allocated sum = `8.0`
  - state summary allocated quantity = `8.0`
  - equality: `true`
- Note: probe rows are intentionally synthetic and not part of final-demand lineage rows; therefore `lineage_consistent=false` for that probe row is expected and does not indicate allocation parity failure.

### Browser/E2E visibility extension
- Updated and executed Playwright certification suite:
  - `frontend/disaster-frontend/e2e/ui-certification.spec.ts`
  - Result: `6 passed`
- Added checks:
  - state request page exposes lifecycle status set aligned with district request log statuses.
  - state overview district detail toggle reveals district/resource/time allocation rows (state-level district drilldown equivalent).

### Terminology mapping requested in validation
- `ready` maps to `pending` (request is queued/not yet allocated).
- `allocated` maps directly to `allocated`.
- `returned` maps to allocation slot lifecycle states `partially_returned` and `closed` (after full return/closure).
- `dropped` is not an explicit backend status in current model; closest observable terminal representations are `closed` (slot lifecycle) or effectively zero/empty availability context.
