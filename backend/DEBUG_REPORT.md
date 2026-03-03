# DEBUG_REPORT

## Objective
Provide implementation-grade evidence for:
- Run lifecycle integrity
- Demand/allocation persistence integrity
- Slot conservation
- Dashboard run selection consistency

## Files Changed

### Backend service hardening
- `app/services/request_service.py`
- `app/services/scenario_runner.py`

### Diagnostic/evidence harness
- `run_sql_baseline_diag.py`
- `run_running_diag.py`
- `run_integrity_debug_suite.py`
- `inspect_recent_runs.py`
- `cleanup_running_live.py`
- `run_live_smoke.py`
- `run_live_coalesce_check.py`

## Phase 1: Before/After SQL Evidence

### Before (captured at baseline)
- Live running row existed: `solver_runs.id=180`, `mode=live`, `status=running`
- Running live row persistence:
  - `final_demands=0`
  - `allocations=0`
- Latest completed live run used by dashboard: `id=121`
- For run `121`:
  - `final_demands=1`
  - `allocations=9`
  - `unmet=3`

### After (post-hardening snapshot)
From `run_sql_baseline_diag.py` + `inspect_recent_runs.py`:

- No active running live rows after cleanup/hardening checks:
  - `RUNNING_LIVE []`
- Latest completed live run remains `121` (no successful new live completion in this test flow)
- Scenario runs (`195`,`196`,`197`) completed with persisted rows:
  - `final_demands`: non-zero
  - `allocations`: non-zero
  - unmet present where expected

## Phase 2: Deterministic Scenario Validation

From latest `debug_suite_results.json`:

### 1) District live test
- `run_id=194`, `status=running`, slot metrics all zero
- Result: **FAIL**
- Interpretation: live-path lifecycle still not completing deterministically in this scripted environment

### 2) State cover
- `run_id=195`, `status=completed`
- Metrics: `final=10`, `alloc=10`, `unmet=0`, conservation=true
- Result: **PASS**

### 3) National cover
- `run_id=196`, `status=completed`
- Metrics: `final=10`, `alloc=10`, `unmet=0`, conservation=true
- Result: **PASS**

### 4) Full shortage
- `run_id=197`, `status=completed`
- Metrics: `final=100`, `alloc=3`, `unmet=97`, conservation=true
- Result: **PASS**

### 5) Escalation lifecycle
- `pending -> allocated -> allocated`
- Result: **PASS**

## Phase 3: Dashboard Consistency Validation

From `debug_suite_results.json` dashboard block:

- District/state summaries still bound to live completed run `121`
- State rows remain zero for that selected run
- National rows non-zero for run `121`

This is consistent with run-selection semantics (live-completed only) and absence of a newly completed healthy live run.

## Phase 4: Live Run Coalescing Validation

From `run_live_coalesce_check.py`:

- `COALESCE_CHECK {'first_run_id': 200, 'second_run_id': 200, 'same_run': True}`

This validates that burst submissions now reuse the active run instead of killing/restarting it.

## Invariant Matrix

- `single_running_live`: enforced by run coalescing + stale-only failover ✅
- `completed_live_must_have_snapshot`: enforced by `_latest_live_run` invalidation ✅
- `scenario_persistence_nonzero`: verified on runs `195/196/197` ✅
- `slot_conservation`: verified in deterministic scenarios ✅
- `dashboard_nonzero_when_demand_exists`: conditional on fresh completed live run; currently blocked by live-path non-completion ⚠️

## Residual Risk

Live runs can remain non-terminal in certain execution contexts; when that happens, dashboards remain on last valid completed live run. Hardening now prevents burst-triggered run thrashing, stale running buildup, and invalid completed-run selection, but a robust live execution strategy (durable queue/worker process) is still recommended for guaranteed completion semantics.

## Final Assessment

- Core optimization + ingest path: **healthy**
- Primary defect class: **live run lifecycle/orchestration**, not solver math
- Hardening status: **applied and validated for selection/isolation invariants**
- Remaining blocker for non-zero live dashboard KPIs: **lack of newly completed live run** in this validation sequence
