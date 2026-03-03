    # Full Frontend Interaction Validation Report

    Generated: 2026-03-01
    Mode: UI-only interaction campaign (no source edits, no DB patching, no API bypass in test actions)

    ## Execution Summary
    - Playwright e2e executed: 20 tests total, 5 passed, 12 failed, 3 skipped.
    - Autonomous UI auditor executed against live frontend/backend.
    - Existing admin smoke evidence reviewed for solver summary fields and revert verification.

    Artifacts:
    - Playwright output: [frontend/disaster-frontend/test-results](frontend/disaster-frontend/test-results)
    - Playwright HTML report: [frontend/disaster-frontend/playwright-report](frontend/disaster-frontend/playwright-report)
    - UI auditor JSON: [backend/ui_audit_results.json](backend/ui_audit_results.json)
    - UI auditor Markdown: [backend/UI_AUDIT_REPORT.md](backend/UI_AUDIT_REPORT.md)
    - Admin smoke report: [backend/ADMIN_DASHBOARD_SMOKE_REPORT.md](backend/ADMIN_DASHBOARD_SMOKE_REPORT.md)

    ## Environment Findings Impacting Coverage
    - Role login instability for many Playwright specs (district/state/national redirects remained on `/login` in several tests).
    - Admin login failed in autonomous auditor role matrix (timeouts for `admin`, `admin_user`, `verify_admin`).
    - Multiple transient `net::ERR_ABORTED` backend requests observed in auditor run.
    - Because of the above, several campaign items are marked BLOCKED/INCONCLUSIVE rather than PASS/FAIL.

    ## Per-Test Results (Required Format)

    ### Test 1
    Test ID: 1
    Scenario ID: N/A
    Selected State: 33 (planned)
    Selected Districts: 602–633 (planned)
    Modeling Mode: Manual (planned)
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: PARTIAL
    Performance Notes: Not executed due admin flow instability
    Result: BLOCKED

    ### Test 2
    Test ID: 2
    Scenario ID: N/A
    Selected State: 33
    Selected Districts: 603
    Modeling Mode: Manual
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: PARTIAL
    Performance Notes: Not executed end-to-end
    Result: BLOCKED

    ### Test 3
    Test ID: 3
    Scenario ID: N/A
    Selected State: 33
    Selected Districts: 603,610,620
    Modeling Mode: Manual
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: PARTIAL
    Performance Notes: Not executed end-to-end
    Result: BLOCKED

    ### Test 4
    Test ID: 4
    Scenario ID: N/A
    Selected State: Kerala (planned)
    Selected Districts: All Kerala (planned)
    Modeling Mode: Guided Random
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: PARTIAL
    Performance Notes: Not executed end-to-end
    Result: BLOCKED

    ### Test 5
    Test ID: 5
    Scenario ID: N/A
    Selected State: Multi-state (planned)
    Selected Districts: Mixed (planned)
    Modeling Mode: Manual
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: PARTIAL
    Performance Notes: Not executed end-to-end
    Result: BLOCKED

    ### Test 6
    Test ID: 6
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Guided Random
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Admin randomizer UI interaction not fully executed by current run set
    Result: BLOCKED

    ### Test 7
    Test ID: 7
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Guided Random
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Apply path not fully covered by active UI suite
    Result: BLOCKED

    ### Test 8
    Test ID: 8
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Guided Random
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Guardrail error case not covered
    Result: BLOCKED

    ### Test 9
    Test ID: 9
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Guided Random
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Guardrail error case not covered
    Result: BLOCKED

    ### Test 10
    Test ID: 10
    Scenario ID: 253 (supporting smoke evidence)
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Guided Random (extreme preset)
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: 959
    Districts Covered: Present in summary endpoint
    Foreign Districts Found: UNKNOWN
    Escalation Observed: PARTIAL (scope keys include state/national/neighbor_state)
    Scope Breakdown: Present (district/state/neighbor_state/national keys)
    Fairness Metrics: Present (flags=[])
    UI Feedback Present: UNKNOWN
    Performance Notes: Evidence from smoke summary endpoint, not full UI path
    Result: INCONCLUSIVE

    ### Test 11
    Test ID: 11
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Manual
    Random Seed: N/A
    Stock Overrides: Planned district zero
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Not executed
    Result: BLOCKED

    ### Test 12
    Test ID: 12
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Manual
    Random Seed: N/A
    Stock Overrides: Planned district+state zero
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Not executed
    Result: BLOCKED

    ### Test 13
    Test ID: 13
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Manual
    Random Seed: N/A
    Stock Overrides: Planned all zero
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Not executed
    Result: BLOCKED

    ### Test 14
    Test ID: 14
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Manual
    Random Seed: N/A
    Stock Overrides: Planned neighbor high
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Not executed
    Result: BLOCKED

    ### Test 15
    Test ID: 15
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Manual
    Random Seed: N/A
    Stock Overrides: Planned abundant
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Not executed
    Result: BLOCKED

    ### Test 16
    Test ID: 16
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Stock-aware
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Stock-aware path not exercised in current e2e suite
    Result: BLOCKED

    ### Test 17
    Test ID: 17
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Fixed manual quantities
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Not separately exercised
    Result: BLOCKED

    ### Test 18
    Test ID: 18
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Balanced demand
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: N/A
    Performance Notes: Not executed
    Result: BLOCKED

    ### Test 19
    Test ID: 19
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Uneven demand
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: N/A
    Performance Notes: Not executed
    Result: BLOCKED

    ### Test 20
    Test ID: 20
    Scenario ID: 253 (supporting smoke evidence)
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: Multi-time
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: 959
    Districts Covered: Present
    Foreign Districts Found: UNKNOWN
    Escalation Observed: Present in scope keys
    Scope Breakdown: Present
    Fairness Metrics: Present + by_time_rows=5
    UI Feedback Present: UNKNOWN
    Performance Notes: Verified by summary endpoint artifact
    Result: INCONCLUSIVE

    ### Test 21
    Test ID: 21
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: N/A
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: PARTIAL
    Performance Notes: UI spec contains run interactions but many role-login failures prevented deterministic verification
    Result: INCONCLUSIVE

    ### Test 22
    Test ID: 22
    Scenario ID: 253 (supporting smoke evidence)
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: N/A
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: 959
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Revert endpoint succeeds in smoke artifact
    Result: INCONCLUSIVE

    ### Test 23
    Test ID: 23
    Scenario ID: 253
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: N/A
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: 959
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: verify_revert_balance net_total=0.0 in artifact
    Result: PASS

    ### Test 24
    Test ID: 24
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: N/A
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: N/A
    Performance Notes: Not executed at 200-scenario scale in current run
    Result: BLOCKED

    ### Test 25
    Test ID: 25
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: N/A
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: N/A
    Performance Notes: Not executed at 1000-run scale in current run
    Result: BLOCKED

    ### Test 26
    Test ID: 26
    Scenario ID: Live
    Selected State: 33
    Selected Districts: 603
    Modeling Mode: Live district flow
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: Not deterministically captured due failed login path in several specs
    Foreign Districts Found: UNKNOWN
    Escalation Observed: PARTIAL (district lifecycle/claim-return path passed in ui-certification)
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: YES
    Performance Notes: One district lifecycle test passed
    Result: INCONCLUSIVE

    ### Test 27
    Test ID: 27
    Scenario ID: Live
    Selected State: 33
    Selected Districts: N/A
    Modeling Mode: State route
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: UNKNOWN
    Escalation Observed: UNKNOWN
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: NO (state tests mostly failed due login redirect)
    Performance Notes: state cross-role observation passed in one audit split test, others failed
    Result: INCONCLUSIVE

    ### Test 28
    Test ID: 28
    Scenario ID: Live
    Selected State: National
    Selected Districts: N/A
    Modeling Mode: National route
    Random Seed: N/A
    Stock Overrides: None
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: UNKNOWN
    Escalation Observed: UNKNOWN
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: PARTIAL
    Performance Notes: National cross-role observation failed in one suite, separate admin rapid/nav passed
    Result: INCONCLUSIVE

    ### Test 29
    Test ID: 29
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: N/A
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: Zero-demand specific admin scenario case not run
    Result: BLOCKED

    ### Test 30
    Test ID: 30
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: N/A
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: PARTIAL (rapid navigation admin smoke passed)
    Performance Notes: explicit double-click run assertion not separately covered
    Result: INCONCLUSIVE

    ### Test 31
    Test ID: 31
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: mode switch mid-scenario
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: not executed
    Result: BLOCKED

    ### Test 32
    Test ID: 32
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: manual + randomizer conflict
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: overwrite confirmation not verified in current UI run
    Result: BLOCKED

    ### Test 33
    Test ID: 33
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: N/A
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: UNKNOWN
    Performance Notes: agent recommendation scope not validated due admin login failure in auditor
    Result: BLOCKED

    ### Test 34
    Test ID: 34
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: N/A
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: PARTIAL
    Performance Notes: global context consistency not fully asserted due upstream failures
    Result: INCONCLUSIVE

    ### Test 35
    Test ID: 35
    Scenario ID: N/A
    Selected State: N/A
    Selected Districts: N/A
    Modeling Mode: N/A
    Random Seed: N/A
    Stock Overrides: N/A
    Solver Run ID: N/A
    Districts Covered: N/A
    Foreign Districts Found: N/A
    Escalation Observed: N/A
    Scope Breakdown: N/A
    Fairness Metrics: N/A
    UI Feedback Present: PARTIAL
    Performance Notes: audit logging exists, but integrity completeness test not fully executed
    Result: INCONCLUSIVE

    ## Summary Table
    | Category | Passed | Failed | Blocked | Inconclusive | Notes |
    |---|---:|---:|---:|---:|---|
    | Isolation (A) | 0 | 0 | 5 | 0 | Admin scenario flow not fully executable due auth/timeouts |
    | Randomizer UX (B) | 0 | 0 | 4 | 1 | Endpoint evidence exists, full UI proof incomplete |
    | Escalation (C) | 0 | 0 | 5 | 0 | Not fully executed in stable admin scenario path |
    | Stock-aware (D) | 0 | 0 | 2 | 0 | Not covered by current e2e suite |
    | Fairness (E) | 0 | 0 | 2 | 1 | By-time/fairness presence confirmed via summary artifact |
    | Async UX (F) | 1 | 0 | 0 | 2 | Revert verify net zero confirmed; full UI state checks partial |
    | Performance (G) | 0 | 0 | 2 | 0 | Large-scale load tests not run in this pass |
    | Non-admin routes (H) | 0 | 0 | 0 | 3 | Mixed signals due role redirect failures |
    | Edge (I) | 0 | 0 | 4 | 3 | Some smoke evidence, many edge assertions not run |

    ## Isolation Breaches
    - No explicit confirmed cross-state scenario bleed from this UI run set.
    - Isolation could not be fully certified because core admin scenario isolation cases (Tests 1–5) were blocked.

    ## Escalation Failures
    - No definitive functional escalation failure proven from UI-only evidence.
    - Coverage insufficient for certification due blocked scenarios.

    ## Async UX Failures
    - Partial regressions/instability: multiple role flows returned to `/login` after submit.
    - `national` stream request failure observed (`net::ERR_ABORTED`) in ui-certification run.

    ## Performance Regressions
    - Auditor reported many slow responses (>3s) and timeout conditions.
    - Full 200-scenario / 1000-run stress UI checks were not executed.

    ## Recommendation List
    1. Stabilize role login credentials in Playwright helpers and auditor credential matrix for current seeded data.
    2. Resolve backend request aborts/timeouts (`/state/*`, `/metadata/resources`, `/national/allocations/stream`) before rerunning campaign.
    3. Re-run Group A–C first with stable admin auth to certify scenario isolation and escalation.
    4. Add dedicated e2e specs for Tests 8, 9, 16, 17, 24, 25, 30, 31, 32, 33, 34, 35.
    5. Capture per-run district-set and scope/fairness values into machine-readable report rows during UI tests.
