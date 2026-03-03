# Full Frontend Interaction Validation Checklist

Generated: 2026-03-01
Mode: UI-only interaction (no backend code changes, no DB patching, no API bypass)

## Preconditions
- Backend reachable at `http://127.0.0.1:8000`
- Frontend reachable at `http://127.0.0.1:5173` (or update base URL)
- Test accounts available for roles: `admin`, `district`, `state`, `national`
- Playwright dependencies installed
- DB lock free (`start_e2e_backend.py` must complete seeding)

## Execution Command Set
- Start backend seed+server: `python backend/start_e2e_backend.py`
- Start frontend: `npm run dev -- --host=127.0.0.1 --port=5173` (from `frontend/disaster-frontend`)
- Run UI cert suite: `npm run e2e` (from `frontend/disaster-frontend`)
- Run autonomous auditor: `python backend/autonomous_ui_auditor.py`

## Per-Test Evidence Template
```text
Test ID:
Scenario ID:
Selected State:
Selected Districts:
Modeling Mode:
Random Seed:
Stock Overrides:
Solver Run ID:
Districts Covered:
Foreign Districts Found: YES/NO
Escalation Observed:
Scope Breakdown:
Fairness Metrics:
UI Feedback Present: YES/NO
Performance Notes:
Result: PASS / FAIL
Artifacts: screenshots/report links
```

## Test Matrix (35)
### Group A — Scenario Isolation
- [ ] Test 1 Single State Isolation (Tamil Nadu)
- [ ] Test 2 Single District Only
- [ ] Test 3 Three Custom Districts
- [ ] Test 4 Kerala State Isolation
- [ ] Test 5 Multi-State Scenario (if allowed)

### Group B — Randomizer Behavior
- [ ] Test 6 Preview Randomizer UX
- [ ] Test 7 Apply Randomizer UX
- [ ] Test 8 Randomizer District Count Guardrail
- [ ] Test 9 Randomizer Resource Count Guardrail
- [ ] Test 10 Extreme Preset Escalation

### Group C — Escalation Automation
- [ ] Test 11 District Shortage → State
- [ ] Test 12 State Shortage → National
- [ ] Test 13 Full Shortage → Unmet
- [ ] Test 14 Neighbor Escalation
- [ ] Test 15 Abundant Supply

### Group D — Stock-Aware Randomization
- [ ] Test 16 Stock-Aware ON
- [ ] Test 17 Stock-Aware OFF

### Group E — Fairness Metrics
- [ ] Test 18 Balanced Demand
- [ ] Test 19 Uneven Demand
- [ ] Test 20 Multi-Time Horizon

### Group F — Async UX
- [ ] Test 21 Run Scenario Button Behavior
- [ ] Test 22 Revert Button Behavior
- [ ] Test 23 Verify Revert Net=0

### Group G — Performance
- [ ] Test 24 200 Scenarios Load Performance
- [ ] Test 25 1000 Runs Tab Responsiveness

### Group H — Non-Admin Routes
- [ ] Test 26 District Route Isolation
- [ ] Test 27 State Route Escalation Scope
- [ ] Test 28 National Route Allocation Scope

### Group I — Edge Conditions
- [ ] Test 29 Run With Zero Demand
- [ ] Test 30 Rapid Double Click Run
- [ ] Test 31 Switch Modeling Mode Mid-Scenario
- [ ] Test 32 Manual Demand + Randomizer Conflict
- [ ] Test 33 Agent Recommendation Scope
- [ ] Test 34 Global Operational Context Accuracy
- [ ] Test 35 Audit Log Integrity

## Final Summary Table
| Category | Passed | Failed | Blocked | Notes |
|---|---:|---:|---:|---|
| Isolation |  |  |  |  |
| Randomizer UX |  |  |  |  |
| Escalation |  |  |  |  |
| Fairness |  |  |  |  |
| Async UX |  |  |  |  |
| Performance |  |  |  |  |
| Non-admin routes |  |  |  |  |
| Edge conditions |  |  |  |  |

## Failure/Regression Log
- Isolation breaches:
- Escalation failures:
- Async UX failures:
- Performance regressions:
- Audit inconsistencies:

## Recommendations
- Short-term fixes:
- Medium-term hardening:
- Long-term automation improvements:
