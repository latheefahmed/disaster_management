# Request ↔ Solver Reconciliation Engineering Report

Date: 2026-02-22

## 1) Root Cause

The solver ingest pipeline (`app/engine_bridge/ingest.py`) persisted allocation and unmet rows with `request_id=0` and reconciled only `final_demands`. It did **not** update `requests` rows after ingest.

A separate late-stage status refresher existed in `app/services/request_service.py` (`_refresh_request_statuses_for_latest_live_run`) and was invoked from service/view flows, not as a hard post-ingest stage. This created a correctness gap: requests included in solver runs could remain `pending` with no persisted per-request quantities.

## 2) Files Changed

1. `app/engine_bridge/ingest.py`
2. `app/models/request.py`
3. `app/database.py`
4. `app/services/request_service.py`
5. `tests/test_request_solver_reconciliation.py` (new)

## 3) Implementation Summary

### 3.1 New deterministic reconciliation stage

Added:

- `reconcile_requests_from_solver_run(db, solver_run_id)` in `app/engine_bridge/ingest.py`

Behavior:

- Selects all requests participating in run (`run_id = solver_run_id`, `included_in_run = 1`)
- Aggregates allocations/unmet by:
  - direct `request_id` (authoritative if present)
  - slot-level fallback (`district_code`, `resource_id`, `time`) when ingest rows are unbound (`request_id=0`)
- Distributes slot totals proportionally by request quantity within each slot
- Persists on each request:
  - `allocated_quantity`
  - `unmet_quantity`
  - `final_demand_quantity = allocated + unmet`
  - `status` derived deterministically:
    - allocated if alloc>0 and unmet=0
    - partial if alloc>0 and unmet>0
    - unmet if alloc=0 and unmet>0
    - failed if alloc=0 and unmet=0
  - `lifecycle_state` mirrored deterministically from status

### 3.2 Wired into ingest transaction

`ingest_solver_results(...)` now calls:

1. `reconcile_final_demands_with_allocations(...)`
2. `reconcile_requests_from_solver_run(...)`
3. `db.commit()`

So reconciliation is now a first-class post-solver ingest stage.

### 3.3 Hard invariant enforcement

After reconciliation:

- invariant check: no rows with `run_id=solver_run_id AND included_in_run=1 AND status='pending'`
- on violation:
  - mark run status as `failed_reconciliation`
  - raise `RuntimeError`

## 4) State Model Decision

Both `status` and `lifecycle_state` are retained for compatibility.

Authoritative business state remains `status`.

`lifecycle_state` is deterministically mirrored from `status` for solved/terminal states:

- `allocated -> ALLOCATED`
- `partial -> PARTIAL`
- `unmet -> UNMET`
- `failed -> FAILED`

(Also aligned existing mapper in `request_service` and runtime backfill in `database.py` to map `failed -> FAILED`.)

## 5) Schema Hardening

Added durable request fields:

- `allocated_quantity REAL NOT NULL DEFAULT 0.0`
- `unmet_quantity REAL NOT NULL DEFAULT 0.0`
- `final_demand_quantity REAL NOT NULL DEFAULT 0.0`

In both:

- SQLAlchemy model (`app/models/request.py`)
- SQLite runtime migration (`app/database.py`)

## 6) Regression Tests Added

New file: `tests/test_request_solver_reconciliation.py`

Tests:

1. `test_solver_reconciliation_allocated_status`
2. `test_solver_reconciliation_unmet_status`
3. `test_solver_reconciliation_partial_status`

Assertions include:

- request transitions out of `pending`
- status correctness (`allocated`, `unmet`, `partial`)
- conservation: `allocated_quantity + unmet_quantity == final_demand_quantity`

## 7) Evidence Logs

Command:

`$env:PYTHONPATH='.'; pytest -q tests/test_request_solver_reconciliation.py`

Result:

- `3 passed, 10 warnings in 1.88s`

Compatibility spot-check:

Command:

`$env:PYTHONPATH='.'; pytest -q tests/test_system_stabilization_regression.py::test_request_reconciliation_time_match`

Result:

- `1 passed, 9 warnings in 4.62s`

## 8) Why This Will Not Regress

- Reconciliation is executed in ingest transaction immediately after solver output persistence.
- Post-reconcile invariant is hard-failed (`RuntimeError`) with explicit run status (`failed_reconciliation`), preventing silent drift.
- Regression tests codify allocated/unmet/partial status mapping and conservation equation.
- Request quantity fields are now persisted as first-class DB columns rather than inferred-only view values.
