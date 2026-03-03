# District 603 Under-Stock Allocation Confirmation

Generated: 2026-02-22

## Run Attempt

- Solver run id: 2
- Solver status: running (did not complete during polling window)
- Poll duration: 120 seconds (40 checks x 3s)

## Quantity Check (District 603, time=0)

- Allocated quantity: 0.0
- Unmet quantity: 0.0

## Confirmation Verdict

- **FAIL (cannot confirm full allocation)**

## Justification

- The run never reached `completed` or `failed`; it remained `running` throughout polling.
- No allocation rows were produced for run 2 during the polling window.
- Because the solver run is incomplete, there is no valid basis to claim “all requested quantities got allocated and nothing went unmet.”

## Supporting Evidence

- DB snapshot at end of polling:
  - `solver_runs.id=2 status=running`
  - `allocations for run 2 = 0 rows`
  - `district 603 allocated sum = 0.0`
  - `district 603 unmet sum = 0.0`
