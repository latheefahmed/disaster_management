# Error / Runtime Notes

## Observed issues in this session
- Temporary backend process/port confusion during validation (stale uvicorn processes on previously used ports).
- Frontend was temporarily unreachable until Vite was restarted.
- Generated a large number of runtime artifacts/logs during stress runs.

## Impact
- No blocker remains for code continuation.
- Validation eventually completed successfully after process cleanup/restart.

## Important artifact categories currently in working tree
- Runtime/log artifacts (safe to exclude from commits unless explicitly needed):
  - `uvicorn_*.out.log`, `uvicorn_*.err.log`
  - `../core_engine/phase4/logs/ingest_rejected_rows_run_*.json`
  - `../core_engine/phase4/scenarios/generated/scenario_*_demand.csv`
  - transient SQLite sidecars (`backend.db-shm`, `backend.db-wal`)

## Recommendation for clean operation
- Keep source/report changes in git.
- Avoid committing transient run outputs unless required for evidence.
- If runtime behaves unexpectedly, stop old backend/frontend processes before restarting.
