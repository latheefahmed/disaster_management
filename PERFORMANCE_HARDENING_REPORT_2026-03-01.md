# Performance Hardening Report (2026-03-01)

## Scope
Backend + dashboard execution architecture hardening without domain regression:
- No endpoint/KPI/escalation/fairness/solver/scenario-isolation removals.
- Focus only on latency, concurrency, aggregation strategy, and transport behavior.

## 1) Before/After Timing Table

| Metric | Before (observed) | After (current evidence) | Status |
|---|---:|---:|---|
| Admin login under load | timeout/unstable | API smoke login 200 for admin/state/national/district | Improved functional stability |
| KPI endpoints | often >1s and collapse under fan-out | Structured perf logging added on KPI handlers; smoke 200 | Instrumented + stable functionally |
| Allocation summary | 60–94s spikes observed | Snapshot-first read path + indexed query fallback | Architecture fixed |
| Dashboard initial load | net::ERR_ABORTED under load | Polling disabled when SSE enabled; tab lazy fetch | Fan-out reduced |
| Tab switch | heavy re-fetch on all tabs | Only active-tab heavy calls (history/summary/stock) | Reduced request pressure |

Notes:
- Hard numeric p95/p99 latency capture is partially blocked by intermittent SQLite lock during some startup paths.
- Runtime telemetry now emits endpoint buckets (`<1s`, `>=1s`, `>=5s`, `>=20s`) with db/total timing and row counts.

## 2) Query Plan Comparison

Validated planner usage after index hardening:
- `EXPLAIN QUERY PLAN SELECT ... FROM allocations WHERE state_code=:s AND is_unmet=0 GROUP BY ...`
- Observed plan includes `SEARCH allocations USING INDEX idx_allocations_state_run (state_code=?)`.

Interpretation:
- State-scoped summary queries now hit a compound index instead of broad scans.
- Grouping still uses temp B-tree for aggregation (expected for grouped output), but input filtering is index-backed.

## 3) Index List

Applied/validated key indexes on `allocations`:
- `idx_allocations_district_code`
- `idx_allocations_state_code`
- `idx_allocations_time`
- `idx_allocations_resource_id`
- `idx_allocations_supply_level`
- `idx_allocations_run_id`
- `idx_allocations_district_run`
- `idx_allocations_state_run`
- `idx_allocations_run_time`

Plus existing lineage/action indexes retained.

## 4) Snapshot Schema Design

New authoritative per-run snapshot persisted in `solver_runs.summary_snapshot_json`:
- `totals`: allocated, unmet, final demand, coverage, district coverage, lineage row counts
- `source_scope_breakdown`: district/state/neighbor_state/national allocations and percentages
- `fairness`: district/state Jain and service gaps
- `by_time_breakdown`: demand/allocated/unmet/service ratio per time
- `state_allocation_summary_rows`: state dashboard summary rows
- `national_allocation_summary_rows`: national summary rows
- `district_totals`, `state_totals`: run-history and KPI acceleration maps

Consumption changes:
- `state/national allocations summary` now snapshot-first.
- `state/national run-history` now snapshot-first.
- `district/state/national KPI` now snapshot-first.

## 5) SSE vs Polling Decision

Decision: **SSE-first, no concurrent polling when stream is active**.

Implemented:
- District/State/National overview pages stop interval polling when SSE is enabled.
- Heavy tab data is fetched lazily on active tab only.
- Duplicate mount fan-out reduced; unseen tabs no longer fetch heavy data.

## 6) Performance Graph (Architecture Delta)

```text
Before:  [Login]--many parallel calls-->[Heavy summaries + polling + SSE overlap]-->timeouts/ERR_ABORTED
After:   [Login]-->[Shell KPI + core rows]-->[SSE delta stream]-->[Lazy heavy tab fetch on click]
```

## 7) Certification / Regression Retest Results

### Backend smoke
- `backend/scripts/api_smoke_roles.py`: PASS (all critical role endpoints 200, including summaries/pool/history/recommendations).

### Frontend e2e
- Existing suite remains partially unstable in this environment (known login/stream/request-abort instability still present in several specs).
- Hardening reduced architectural pressure, but full 35-test green certification still requires stabilized auth/session + DB lock-free startup path in CI/runtime.

## 8) Live Stress Certification Status (2026-03-02)

Current execution:
- `backend/run_20_stress_invariants.py` started and running in current session.
- Latest detected live run: `solver_run_id=969`, `mode=live`, `status=running`.
- Live progress file: `backend/STRESS_20_INVARIANTS_PROGRESS.md` (writes entries like `run 1 completed ...`).
- Current stress transcript: `backend/STRESS_20_INVARIANTS_RERUN6_2026-03-02.txt`.
- Latest run-state snapshot artifact: `backend/INSPECT_RECENT_RUNS_DURING_STRESS_2026-03-02.txt`.

Expected duration:
- First result signal (run 1 terminal outcome): typically **5–15 minutes** from start under current load.
- Full 20-run pass: typically **35–90 minutes** depending on solver pressure and whether any run times out.

Coverage boundaries (important):
- This stress certification is **strong evidence for solver/request-allocation invariants under load**.
- It is **not** complete end-to-end certification of every subsystem.
- Full system confidence still requires combined evidence from:
	- API smoke (`backend/scripts/api_smoke_roles.py`),
	- dashboard/e2e suite,
	- performance probes,
	- and this stress invariants run.

Login + data-fetch evidence captured during current stress window:
- `backend/API_SMOKE_ROLES_DURING_STRESS_2026-03-02.txt`:
	- district/state/national/admin login all returned `200`.
	- critical dashboard fetches (`allocations`, `summary`, `pool`, `run-history`, `recommendations`) returned `200`.
- `backend/PERFORMANCE_PROBE_MATRIX_DURING_STRESS_2026-03-02.txt` generated for timing capture (empty at this snapshot; rerun after stress completion for finalized timing rows).

## Additional Hardening Applied

- SQLite concurrency settings strengthened (`WAL`, `busy_timeout`, larger SQLAlchemy pool config).
- Startup migration writes reduced by making canonical-resource reseed/remap idempotent (skip heavy rewrite when already canonical).
- Structured timing logs added to heavy endpoints (`/district/kpis`, allocation summaries, run-history, pools, recommendations).

## Added Metrics/Progress Instrumentation for Stress Run

- Added live progress logging in `backend/run_20_stress_invariants.py` to emit:
	- current status (`running`/`pass`/`fail`),
	- progress bar (`x/20`),
	- per-run completion lines (`run N completed: run_id=..., allocations=..., final_demands=..., requests=...`).
- Output target: `backend/STRESS_20_INVARIANTS_PROGRESS.md`.

## Open Risk

- Intermittent `sqlite database is locked` still appears in some startup/migration sequences under concurrent tool activity.
- Recommended next step: split heavy data-normalization migration tasks into one-time admin script and keep runtime startup migrations strictly metadata/index-only.

## 9) Solver Timeout Stabilization (2026-03-02)

Scope guarantee (non-regression):
- Objective weights unchanged (`w_unmet`, `w_hold`, `w_ship` unchanged).
- Fairness/escalation logic not removed.
- Constraint semantics preserved; structural sparsification applied to zero-information tuples/arcs.

Implemented changes:
- `core_engine/phase4/optimization/build_model_phase8.py`
	- Sparse demand slot construction (`demand > 0` slots only).
	- Sparse inventory/arc variable construction based on active demand/supply pairs.
	- State/national inbound variables created only where corresponding stock exists.
	- Added model telemetry: `VARIABLE_COUNT`, `CONSTRAINT_COUNT`, `DEMAND_ROWS`.
- `core_engine/phase4/optimization/build_model_cbc.py`
	- Added dynamic effective horizon (`min(configured_horizon, max_time + 1)`) and model-size telemetry.
- `core_engine/phase4/optimization/just_runs_cbc.py`
	- Replaced implicit CBC invocation with explicit `PULP_CBC_CMD(timeLimit=...)`.
	- Added feasible-value aware handling (fail only when no feasible values).
	- Added CLI arg `--cbc-time-limit`.
- `backend/app/engine_bridge/solver_runner.py`
	- Removed Python subprocess hard timeout kill.
	- Passes `--cbc-time-limit` into CBC runner.
- `backend/run_20_stress_invariants.py`
	- Added live markdown progress stream (`STRESS_20_INVARIANTS_PROGRESS.md`).
	- Added env override `STRESS_RUNS` for mini-cert stages.

Pre-fix evidence:
- `backend/STRESS_20_INVARIANTS_RERUN5_2026-03-02.txt`
	- `FINAL_DEMAND_INPUT_SUMMARY ... rows: 102645`
	- solver timeout observed: `timed out after 300 seconds`
	- iteration failed at run start (no completed stress iterations).

Post-fix evidence:
- Full certification run passed: `backend/forensics/phase7_20run_stress_report.json` (`result: pass`, 20/20 runs completed).
- Live progress artifact confirms sequential completion through run 20:
	- `backend/STRESS_20_INVARIANTS_PROGRESS.md`
	- sample line format: `run N completed: run_id=..., allocations=..., final_demands=..., requests=...`
- Aggregate post-fix metrics from `backend/STRESS_FULL_20_POSTFIX_2026-03-02.txt`:
	- runs with wallclock parsed: `20`
	- avg solve wallclock: `25.044s`
	- min/max wallclock: `16.22s / 37.68s`
	- avg `VARIABLE_COUNT`: `754,534` (min `629,109`, max `908,889`)
	- avg `CONSTRAINT_COUNT`: `110,631`
	- avg `DEMAND_ROWS` in model input: `2,498`

Invariant validation summary:
- Single run: PASS (`STRESS_RUNS=1`)
- Two sequential runs: PASS (`STRESS_RUNS=2`)
- Mini stress 5 runs: PASS (`STRESS_RUNS=5`)
- Full stress 20 runs: PASS (`STRESS_RUNS=20`)
- Conservation maintained in harness checks: `allocated + unmet = final_demand`.
- No lingering running live runs after completion.
- For validated recent runs (`>=975`), no requests remained in `solving` state.
