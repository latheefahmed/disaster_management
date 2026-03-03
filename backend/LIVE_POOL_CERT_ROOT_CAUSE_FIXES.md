# LIVE Pool Certification: Root Cause & Fixes (Brief)

## What was going wrong

1. `/district/run` was effectively blocking
- `trigger_live_solver_run -> _start_live_solver_run` called `_run_solver_job(...)` inline.
- API caller waited for heavy solver/ingest path and often hit read timeout.
- Certification runner appeared stuck at `Attempt X: triggering solver`.

2. Invalid request state refresh for non-run requests
- In `_refresh_request_statuses_for_latest_live_run`, requests with `run_id=0` could be left as `solving` with `queued=true`, `included_in_run=false`.
- This created stale backlog and lifecycle inconsistency.

3. One bad subset could fail entire solver run
- In `_run_solver_job`, included requests with zero final demand raised hard `ValueError`, failing the full run repeatedly.

4. Certification counting semantics were misleading
- `completed_runs` was tied to `solver_status == completed`, not true end-to-end validation.

5. False conservation failures for escalated requests
- Some runs ended with `request_status=escalated_national` and no district-scope alloc/unmet rows for that request slot.
- Harness still enforced strict local conservation against district-row evidence and flagged `conservation_failed`.
- These were state/scope mismatches, not true solver execution failures.

## Root-cause fixes applied

### Backend (`app/services/request_service.py`)
- Made live solver trigger non-blocking:
  - `_start_live_solver_run` now starts `_run_solver_job` in a daemon thread.
  - `/district/run` returns quickly with `solver_run_id` while status remains `running`.
- Fixed status refresh for non-run requests:
  - For `run_id <= 0`, stale `solving` rows are healed to `pending`, `lifecycle_state=CREATED`, `queued=1`, `included_in_run=0`.
- Improved non-completed run normalization:
  - For in-run rows (`run_id>0` + run not completed), ensure `status=solving`, `included_in_run=1`, `queued=0`.
- Replaced hard abort on zero-final-demand subset:
  - Quarantine only invalid request IDs (`failed/UNMET/run_id=0`) and continue processing the run.

### Certification harness (`run_live_pool_certification.py`)
- Hardened run binding and progress semantics:
  - Added run-id-bound polling via `/district/run-history` and request terminal wait.
  - Uses `/district/unmet` for unmet evidence.
  - Counts `completed_runs` as `invariants_pass == true` (and tracks `solver_completed_runs` separately).
- Added stricter invariant gates:
  - Requires completed solver, terminal request state, inclusion in run, non-negative stock, and provenance checks.

- Added escalation-aware invariant scope:
  - Conservation is required only for local fulfillment statuses (`allocated`, `partial`, `unmet`, `failed`).
  - Escalated states (`escalated_state`, `escalated_national`) no longer fail on missing district-scope alloc/unmet rows.
  - Escalation path is inferred from request terminal status when allocation-source rows are empty.

## Verification done

- Code compile checks passed for patched files.
- Backend restarted with patched code.
- Post-fix smoke cert run completed without trigger hang:
  - `target=3`, `max_attempts=8`
  - Result: `completed_runs=3`, `solver_completed_runs=3`, `invariant_violations=0`.

## Current status

- The original “stuck at triggering solver / long timeout” root issue is fixed.
- The system now progresses run-by-run predictably.
- Full 60-run campaign can be executed next with these fixes.

## Future failure spectrum & preventive fixes

1. Long-running solver runs / API timeout windows
- Symptom: trigger appears stuck, polling long in `running`.
- Prevention: keep `/district/run` non-blocking; use run-id-bound polling with bounded waits and explicit timeout statuses.

2. State refresh drift (`run_id=0` rows becoming `solving`)
- Symptom: backlog of `solving + queued + not included` rows.
- Prevention: keep refresh logic partitioned by `run_id` domain; heal stale non-run rows to `pending/CREATED`.

3. Mixed-scope evidence mismatch (district vs escalated lifecycle)
- Symptom: conservation false negatives on escalated requests.
- Prevention: keep invariant checks scoped by terminal lifecycle state.

4. Monolithic solver job coupling risk
- Symptom: one bad request aborts whole run.
- Prevention: quarantine invalid subsets and continue; isolate request-level failures from run-level failures.

5. Operational modularity opportunities
- Split runner concerns into modules: `run_trigger.py`, `evidence_collection.py`, `invariants.py`, `restoration.py`.
- Add contract tests for endpoint payload semantics (`/allocations`, `/unmet`, `/requests`, `/run-history`).
- Add a small health gate before campaigns: backend reachability, single-server process check, stale-running-run detector.
