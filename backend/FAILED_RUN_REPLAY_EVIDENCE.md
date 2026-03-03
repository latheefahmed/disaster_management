# Failed Run Replay Evidence

Generated: 2026-02-25

## Historical failed run (selected)
- run_id: 370
- status: failed
- mode: live
- started_at: 2026-02-25T15:36:00.430330
- total_demand: 220.0
- total_allocated: 0.0
- total_unmet: 0.0
- allocation_rows: 0
- unmet_rows: 0

## Replay run executed now
- trigger response: `{"status": "accepted", "solver_run_id": 517, "requested_by": "603"}`
- run_id: 517
- elapsed_to_terminal: 0.73s
- status: completed
- mode: live
- started_at: 2026-02-25T17:09:16.381758
- total_demand: 0.0
- total_allocated: 0.0
- total_unmet: 0.0
- allocation_rows: 0
- unmet_rows: 0

## Side-by-side conclusion
- One historical failed live run was replayed through the same `/district/run` path.
- Replay reached terminal state quickly and completed (not failed).
- Evidence is consistent with the recent fix where empty/no-pending live triggers no longer fail and now complete as no-op runs.
