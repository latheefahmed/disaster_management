# District 603 Stabilization Report (2026-03-05)

## Scope
This report documents the final stabilization pass for district 603 live operations, including:
- failed live-run lifecycle correction
- district run visibility/ordering fixes
- failed live-run database cleanup
- post-cleanup smoke verification (including medical kits)
- oxygen `>=50001` trace clarification

## Code Fixes Applied

### 1) Failed run lifecycle handling
File: `backend/app/services/request_service.py`
- Updated live-run refresh behavior so requests tied to failed live runs are set to failed lifecycle semantics instead of being left in a solving loop.
- Prevents requests from appearing to regress/disappear due to stale `solving` status after failure.

### 2) Escalation sequencing adjustment
File: `backend/app/services/request_service.py`
- Adjusted escalation flow to avoid immediate escalation to national when accepted state/neighbor aid in the same cycle reduces unmet quantity.
- Keeps escalation behavior aligned with the intended chain: local/state/neighbor before national where feasible.

### 3) District run status and history visibility
File: `backend/app/routers/district.py`
- `GET /district/solver-status` now resolves against latest live run (not only latest completed historical snapshot path).
- `GET /district/run-history` includes live runs regardless of completion state, improving visibility during/after failures.

### 4) District dashboard initial refresh timing
File: `frontend/disaster-frontend/src/dashboards/district/DistrictOverview.tsx`
- Added `overviewBoot` as a dependency in the initial fetch effect to force timely first refresh.
- Reduces stale first-load behavior and improves ordering/freshness perception.

### 5) Ingest serialization hardening (runtime blocker)
File: `backend/app/engine_bridge/ingest.py`
- Ensured rejected-row JSON serialization handles datetime values (`default=str`), preventing hidden crash paths during high-volume runs.

## Failed Live-Run Cleanup (Executed)
Source evidence: `backend/FAILED_LIVE_RUNS_CLEANUP_REPORT_2026-03-05.json`

- Failed live runs before cleanup: `102`
- Failed live runs after cleanup: `0`
- Failed-run linked allocations deleted: `889`
- Failed run headers deleted: `102`
- Requests requeued from failed runs: `0` (none linked at cleanup time)

Result: historical failed live-run clutter was removed from runtime-facing data paths.

## Post-Cleanup Verification

### Smoke run
Source evidence: `backend/D603_SMOKE_TRACE_REPORT_2026-03-05.json`

- New solver run created: `1209`
- Run status: `completed`
- Coverage: `1.0`
- District 603 smoke items (including medical kits) all allocated with zero unmet.

District 603 resource rows in run `1209` include:
- `R14` medical kits: allocated `25.0`
- `R21` oxygen cylinders: allocated `80.0`
- plus `R1`, `R2`, `R10`, `R13`, `R16`, `R20` all fully allocated.

### Allocation ordering
From smoke report:
- `alloc_order_latest_first = true`

### District API visibility check
Manual API verification after cleanup:
- `GET /district/solver-status` returns run `1209`, status `completed`, mode `live`
- `GET /district/run-history?page=1&page_size=10` returns latest-first list headed by `1209`, `1208`, `1207`

## Oxygen 50001 Clarification
Source evidence: `backend/D603_SMOKE_TRACE_REPORT_2026-03-05.json` (`oxygen_50001_trace`)

Traced request:
- request id: `3355`
- resource: `R21` (oxygen cylinders)
- quantity: `53766.0`
- run id: `1127`
- status: `allocated`
- allocated: `53766.0`
- unmet: `0.0`

Source breakdown:
- district: `12727.0`
- state: `41039.0`
- neighbor_state: `0.0`
- national: `0.0`

Interpretation:
- This high-volume oxygen request was fully satisfied using district + same-state supply.
- No neighbor-state or national allocation was required for this traced case.

## Final Outcome
- District 603 disappearing/failed-run visibility symptoms were addressed via lifecycle and run-selection fixes.
- Failed live-run data clutter was cleaned from the DB.
- Latest allocation ordering validated as latest-first.
- Medical kits and oxygen smoke flows verified post-cleanup.
- Oxygen `>=50001` case confirmed fully allocated with district+state contribution and no national usage.
