# FINAL_STABILITY_REPORT

## Execution Summary
Generated from latest evidence artifacts:
- `stability_evidence.json` at `2026-02-21T07:49:13.729099+00:00`
- `expanded_matrix_verification.json` at `2026-02-21T07:53:59.243492+00:00`
- targeted regression tests at `2026-02-21T07:47:43+00:00` (`18/18` passed)

## Baseline to Current
- Latest completed live runs: `16`, `15`.
- Recent sequence (top):
  - `16 live completed`
  - `15 live completed`
  - `14 scenario completed`
  - `13 scenario completed`
  - `12 scenario completed`

## Analytics Snapshot
- **Invariant checks:** `6/6` passed (`100.0%`)
- **Expanded role+wiring checks:** `55/55` passed (`100.0%`)
- **Targeted backend tests:** `18/18` passed (`100.0%`)
- **Recent run completion (latest 10 runs):** `7 completed / 10 total` (`70.0%`)
- **Live solve persistence efficiency:** `35145 allocations / 35145 final_demands = 100.0%`

## Invariant Evidence

### 1) Auto-allocation from state stock (no escalation gate)
Case: `state_autopull`
- District: `228`, State: `10`, Resource: `R10`
- Demand: `1.0`
- State stock: `334.0`, National stock: `0.0`
- Observed:
  - Final demand: `1.0`
  - Allocated: `1.0`
  - Unmet: `0.0`
  - Supply-level breakdown: `{ state: 1.0 }`
  - Conservation: `allocated + unmet = final` ✅

### 2) Auto-allocation from national stock (no escalation gate)
Case: `national_autopull`
- District: `496`, State: `26`, Resource: `R9`
- Demand: `1.0`
- State stock: `0.0`, National stock: `4562.0`
- Observed:
  - Final demand: `1.0`
  - Allocated: `1.0`
  - Unmet: `0.0`
  - Supply-level breakdown: `{ national: 1.0 }`
  - Conservation: `allocated + unmet = final` ✅

### 3) Full shortage behavior with conservation
Case: `full_shortage`
- District: `228`, State: `10`, Resource: `R10`
- Demand: `335.0`
- State stock: `334.0`, National stock: `0.0`
- Observed:
  - Final demand: `335.0`
  - Allocated: `334.0`
  - Unmet: `1.0`
  - Supply-level breakdown: `{ state: 334.0, unmet: 1.0 }`
  - Conservation: `allocated + unmet = final` ✅

### 4) Live solver determinism
Case: `live_run`
- Run ID: `15`
- Status: `completed`
- Persisted rows:
  - `final_demands = 35145`
  - `allocations = 35145`
- Result: live run completes with non-zero persistence ✅

### 5) Dashboard fallback binding
Case: `dashboard_fallback`
- Latest completed live before flip: `{ id: 16, mode: live }`
- Latest completed any before flip: `{ id: 16, mode: live }`
- Selection when live completed absent: `{ id: 14, mode: scenario }`
- Result: fallback to latest completed any-mode works ✅

### 6) Escalation non-blocking
Case: `escalation_non_blocking`
- Request ID: `7`
- Status after escalate: `allocated`
- Rerun ID: `16`
- Request status after rerun: `allocated`
- Slot metrics:
  - Final: `18.022356`
  - Allocated: `18.022356`
  - Unmet: `0.0`
  - Supply-level: `{ district: 18.022356 }`
  - Conservation: ✅

## SQL-style Snapshot (Current)
- Live runs are completing (`15`, `16`), not stuck in perpetual `running`.
- Completed live run has non-zero `final_demands` and `allocations`.
- Scenario evidence confirms state and national pull paths.

## Expanded Matrix + Wiring Validation
- Coverage:
  - districts covered: `7`
  - states covered: `2`
  - resources checked: `14`
  - scenario demand rows inserted: `98`
- Role/button flow pass totals:
  - district endpoints: `35/35`
  - district actions (claim/consume/return/lists): `7/7`
  - state actions (pool allocate flow): `4/4`
  - national actions (pool allocate flow): `3/3`
  - mutual aid flow: `2/2`
  - frontend wiring checks: `4/4`
- Aggregate expanded pass rate: `55/55 = 100.0%`

## Failed Issue Fixed in This Run
- Root cause fixed: ingest mismatch filter was dropping all rows when `final_demands` snapshot was absent for a run.
- Patch: mismatch rejection now executes only when `final_demand_map` is non-empty.
- File: `backend/app/engine_bridge/ingest.py`
- Validation: previously failing test now passes (`tests/test_system_hardening.py::test_ingest_creates_allocations_and_unmet_rows`).

## Code-level Stabilization Applied
- `backend/app/services/request_service.py`
  - Live runs execute synchronously (no thread launch).
  - Heavy NN/feature context path gated to `ENABLE_NN_META_CONTROLLER`.
- `backend/app/services/scenario_runner.py`
  - Stale-only live cleanup policy.
- `backend/app/services/allocation_service.py`
  - Latest-completed-run fallback helper used for any-mode selection.
- `backend/app/routers/district.py`
  - Run selection for district allocations/unmet/status follows latest completed run semantics.

## Artifacts
- Evidence JSON: `backend/stability_evidence.json`
- Expanded matrix JSON: `backend/expanded_matrix_verification.json`
- This report: `backend/FINAL_STABILITY_REPORT.md`

## Remaining Open Risks
- Pydantic v2 deprecation warnings remain in schema config usage (`Config`/`orm_mode`) and are non-blocking for current behavior.
- Some historical runs are intentionally marked failed during fallback validation; this affects historical completion ratio but not current live determinism.

