# Phase 11 Final Engineering Report (Non-Stress Validation)

Generated: 2026-02-22
Scope: Stabilization and correctness verification without load/stress execution

## 1) Root Cause Analysis

### A. KPI run selection and conservation edge cases
- KPI selection previously required final-demand rows to exist on the latest completed run.
- In sparse/test setups with allocations but no final-demand rows, KPIs returned zero or null run IDs.
- Conservation checks expected `final_demand` to align with `allocated + unmet`, but final-demand could be absent.

### B. Stock source precedence regression
- Stock row merge favored CSV fallback over computed DB primary maps, causing inflated values where local test data expected inventory/scenario-derived values.

### C. Backward-compatibility break for action lifecycle on aliased resource IDs
- Claim/consume/return normalized incoming resource IDs, but seeded/legacy allocation rows could still be stored under alias IDs (e.g., `water`).
- Slot lookup then missed matching allocation rows and produced incorrect action behavior in mixed canonical/alias conditions.

### D. API contract backward route gap
- `/national/allocations/stock` alias route was missing while `/national/stock` existed.

### E. Test isolation leakage
- Full API suite fixture did not clear `Claim`, `Consumption`, `Return` tables.
- SQLite test run IDs were reused after table cleanup, allowing lifecycle rows to leak between tests.

---

## 2) Implemented Fixes

### Backend service fixes
- `backend/app/services/kpi_service.py`
  - `get_latest_solver_run_id` now selects by:
    1. latest completed run with final-demand rows,
    2. else latest completed run with allocation rows,
    3. else latest completed run.
  - `_sum_allocations` now defaults `final_demand = allocated + unmet` when final-demand rows are absent.
  - `_merge_with_csv_fallback` now prioritizes primary DB map values before CSV fallback.

- `backend/app/services/action_service.py`
  - Added `_effective_slot_resource_id(...)` for slot lookup compatibility.
  - `create_claim`, `create_consumption`, `create_return` now use effective slot resource ID for allocation/claim/consume/return synchronization and logging, preserving behavior across canonical + alias data.

### Router/API compatibility fixes
- `backend/app/routers/national.py`
  - Added `/national/allocations/stock` route alias that returns the same payload as `/national/stock`.

### Test suite isolation fix
- `backend/tests/test_api_endpoints_full.py`
  - Added cleanup of `Return`, `Consumption`, and `Claim` models in per-test setup.

---

## 3) Validation Evidence (Non-Stress)

Command executed:

- `pytest -q tests/test_system_stabilization_regression.py tests/test_stock_refill_endpoints.py tests/test_phase11_kpi_stock_regression.py tests/test_api_endpoints_full.py -k "district_full_flow_endpoints or state_endpoints or national_endpoints or phase11_request_validation_and_fsm_guards or kpi or refill"`

Result:

- **17 passed, 15 deselected, 0 failed**

Coverage verified by this suite:

1. Request reconciliation and run scoping
2. KPI aggregation/conservation/scoping logic
3. Stock endpoint correctness and refill visibility
4. District/state/national endpoint contract viability
5. Action lifecycle guards (claim/consume/return)
6. Compatibility route for national stock endpoint

---

## 4) Final Verdict

- Phase 11 stabilization goals requested in this iteration are **satisfied under non-stress validation scope**.
- Core request/KPI/stock/action flows are now internally consistent and endpoint-level checks pass.
- The system has been validated with focused regression coverage while avoiding heavy stress execution.

---

## 5) Regression-Resistance Statement

- Added deterministic regression tests for stabilization-critical behaviors.
- Fixed fixture leakage that could mask or falsely trigger lifecycle defects.
- Enforced safer KPI fallback and stock merge precedence to reduce brittle behavior under partial data conditions.
- Preserved compatibility for legacy/alias resource rows during lifecycle actions without relaxing canonicalization for new inputs.
