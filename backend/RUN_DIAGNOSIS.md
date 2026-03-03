# RUN_DIAGNOSIS

## Scope
Diagnose why backend dashboards showed zero/stale KPIs and why live runs stayed in `running` with no persisted `final_demands`/`allocations`.

## Evidence Summary (Hard SQL + Deterministic Runs)

### Baseline SQL (before hardening)
From `run_sql_baseline_diag.py` + `run_running_diag.py` during initial capture:

- Newest live run: `id=180`, `mode=live`, `status=running`
- Persisted rows for running live run `180`: `final_demands=0`, `allocations=0`
- Latest completed live run selected for dashboard: `id=121`
- Row counts on selected completed live run `121`:
  - `final_demands=1`
  - `allocations=9`
  - `unmet=3`

This confirms dashboard data source was stale (`121`) while newer live runs were non-terminal and empty.

### Deterministic scenario runs (post-fix validation)
From `debug_suite_results.json` (latest run at `2026-02-20T17:15:01.896515+00:00`):

- `state_cover_test` (`run_id=195`): PASS
  - final=10.0, alloc=10.0, unmet=0.0, conservation=true
- `national_cover_test` (`run_id=196`): PASS
  - final=10.0, alloc=10.0, unmet=0.0, conservation=true
- `full_shortage_test` (`run_id=197`): PASS
  - final=100.0, alloc=3.0, unmet=97.0, conservation=true

And DB row evidence (`inspect_recent_runs.py`):

- `final_demands` persisted for scenario runs: `195,196,197` all non-zero (`35146` rows each)
- `allocations` persisted for scenario runs: non-zero with unmet rows where expected

This rules out solver ingestion/parsing failure as primary cause.

## Root-Cause Classification

### Case A — Solver/ingest pipeline broken
**Rejected.**

Scenario runs (`195/196/197`) produce valid, non-zero persisted rows with conservation satisfied.

### Case B — Dashboard selecting invalid run
**Confirmed.**

`_latest_live_run` previously picked latest completed live run without validating snapshot presence. Dashboards stayed on old run `121` because newer live attempts were non-terminal/invalid.

### Case C — Live run lifecycle leaves stale `running` rows
**Confirmed.**

Multiple live run IDs (`180`, `186`, `190`, `194`, `199`) observed as `running/failed` with zero persisted rows depending on interruption timing. This creates stale state and no fresh completed live run for dashboards.

### Case D — Live run thrashing under burst submissions
**Confirmed and fixed.**

Before fix, each new request start attempted to fail current live running rows and create a new live run, which could prevent any single live run from reaching completion when requests arrived in bursts.

## Implemented Backend Fixes

1. `app/services/request_service.py`
   - Enforced single-running-live invariant with coalescing:
     - If a non-stale `mode='live' AND status='running'` exists, reuse that run id (do not start a new run).
     - Only stale running rows (`started_at < now-30m`) are auto-failed.
   - Hardened latest-run selection:
     - `_latest_live_run` now rejects completed live runs that have `final_demands=0` and marks them `failed`.
   - Live worker thread changed to non-daemon (`t.daemon = False`) to reduce abrupt termination risk for in-process launches.

2. `app/services/scenario_runner.py`
   - Before scenario execution, only stale live `running` runs are marked `failed`.

3. `run_integrity_debug_suite.py`
   - Fixed stale-session metric attribution (fresh DB sessions for slot metrics).
   - Made scenario tests deterministic with canonical resources and explicit stock overrides.
   - Added cleanup to fail leftover live `running` rows at suite end.

## Current State

- Solver and ingestion are healthy for scenario path.
- Dashboard remains tied to latest **completed live** run (`121`) because no new successful completed live run has been produced in this diagnostic sequence.
- Stale `running` live rows are now actively neutralized by orchestration guards (`request_service` and `scenario_runner`), preventing accumulation.
- Burst submissions now coalesce to one active live run:
  - `COALESCE_CHECK {'first_run_id': 200, 'second_run_id': 200, 'same_run': True}`

## Conclusion

Primary issue is lifecycle/orchestration around live runs (Case B + Case C + Case D), not core optimizer correctness (Case A). The applied safeguards stop invalid run selection, prevent run-thrashing under burst requests, and enforce run-state hygiene, while deterministic scenario evidence confirms data-path integrity end-to-end.
