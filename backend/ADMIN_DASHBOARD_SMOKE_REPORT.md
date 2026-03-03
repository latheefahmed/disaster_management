# Admin Dashboard Smoke Report

Generated: 2026-03-01T17:24:59.039069+00:00
Overall: **PASS**
Scenario ID: 256
Run ID: 963
Checks: 18 | Pass: 18 | Fail: 0

| Check | Pass | Details |
|---|---|---|
| login_admin | PASS | status=200 |
| list_scenarios | PASS | status=200 |
| create_scenario | PASS | status=200 |
| preview_very_low | PASS | status=200; row_count=264; ratio=0.6101 |
| preview_low | PASS | status=200; row_count=420; ratio=0.9017 |
| preview_medium | PASS | status=200; row_count=312; ratio=1.1713 |
| preview_high | PASS | status=200; row_count=504; ratio=1.5888 |
| preview_extreme | PASS | status=200; row_count=750; ratio=2.3434 |
| apply_randomizer | PASS | status=200; applied_rows=1000 |
| run_scenario | PASS | status=200 |
| list_runs_and_pick_run_id | PASS | status=200; run_id=963 |
| summary_has_by_time_breakdown | PASS | status=200; by_time_rows=5 |
| summary_has_scope_breakdown | PASS | scope_keys=['district', 'national', 'neighbor_state', 'state'] |
| summary_has_fairness_diagnostics | PASS | flags=[] |
| incidents_endpoint_available | PASS | status=200 |
| incidents_payload_shape | PASS | - |
| revert_run_effects | PASS | status=200 |
| verify_revert_balance | PASS | status=200; net_total=0.0 |