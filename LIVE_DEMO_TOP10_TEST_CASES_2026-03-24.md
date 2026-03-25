# Live Demo Top 10 Test Cases (Project Review Pack)

Date: 2026-03-24
Scope: Admin, District, State, National dashboards
Goal: Conclusive live demo script with exact field inputs and expected outputs

## 1) Credentials (use these in Login page)

- Admin:
  - Username: admin
  - Password: admin123
  - Role dropdown: Admin
- District:
  - Username: district_603
  - Password: district123
  - Role dropdown: District
- State:
  - Username: state_33
  - Password: state123
  - Role dropdown: State
- National:
  - Username: national_admin
  - Password: national123
  - Role dropdown: National

## 2) What Was Verified Before Finalizing This Pack

- Fresh admin end-to-end smoke suite: PASS (18/18 checks), including create scenario, 5 randomizer previews, apply, run, incidents, revert, revert verify.
- Fresh district live smoke: PASS (run completed, final demand and allocation created).
- Cross-role API smoke statuses: 200 for district/state/national/admin core endpoints.

Evidence sources used:
- backend/ADMIN_DASHBOARD_SMOKE_REPORT.json (generated_at 2026-03-24)
- backend/API_SMOKE_ROLES_2026-03-01.txt
- backend/run_live_smoke.py live run output (run_id 1769 completed)

## 3) Top 10 Demo Cases

### Case 1 (Admin) - Create Scenario

Dashboard: Admin -> System Health -> Admin Scenario Studio

Inputs:
- New scenario name: review_live_01

Actions:
1. Login as admin.
2. In New scenario name, enter review_live_01.
3. Click Create Scenario.

Expected output:
- Scenario appears in Selected Scenario dropdown.
- Status line updates with a valid scenario id and initial row counts.

---

### Case 2 (Admin) - Manual Demand Batch

Dashboard: Admin -> System Health -> Admin Scenario Studio

Inputs (Hierarchical Selector + Simulation Controls):
- State: 33
- Districts: add at least 603 (and optionally 601/602 if available)
- Resource Types: select R7 and R30 (or any two available resources)
- Scenario Type: Multi District Intra State
- Time Horizon: 3
- Base Demand: 120
- Demand Multiplier: 1.2
- Manual Priority: 4
- Manual Urgency: 4
- Manual Time Index: 1

Actions:
1. Keep Demand Modeling Mode = Manual.
2. Select state, districts, and resources.
3. Click Add Demand Batch.

Expected output:
- Persisted Demand Rows increases above 0.
- Lifecycle state moves from draft to ready.

---

### Case 3 (Admin) - State Stock Override

Dashboard: Admin -> State Stock Override

Inputs:
- state_code: 33
- resource_id: R7
- quantity: 50000

Actions:
1. Fill all 3 fields.
2. Click Add State Stock.

Expected output:
- No validation error.
- Selected scenario status line increments State stock rows.

---

### Case 4 (Admin) - National Stock Override

Dashboard: Admin -> National Stock Override

Inputs:
- resource_id: R52
- quantity: 150000

Actions:
1. Fill both fields.
2. Click Add National Stock.

Expected output:
- No validation error.
- Selected scenario status line increments National stock rows.

---

### Case 5 (Admin) - Guided Randomizer Preview Variations

Dashboard: Admin -> Guided Randomizer

Inputs:
- Demand Modeling Mode: Guided Random
- Demand Level: run these 3 live variations
  - very_low
  - medium
  - high
- Seed: 20279991
- Time Horizon: 5
- Random District Count: 20
- Random Resource Count: 10
- Stress mode: checked
- Quantity mode: Stock-aware distribution

Actions:
1. For each demand level above, click Preview Randomizer.

Expected output:
- Preview box shows row_count > 0 each time.
- Demand/Supply ratio rises from very_low -> medium -> high.

Note from latest verified run:
- very_low ratio 0.2
- medium ratio 1.0
- high ratio 1.5

---

### Case 6 (Admin) - Apply Randomizer, Run Scenario, Inspect, Revert, Verify

Dashboard: Admin -> System Health + Solver Runs

Inputs:
- Reuse Case 5 settings

Actions:
1. Click Apply Randomizer and confirm popup.
2. Click Run Scenario.
3. Open Solver Runs tab and Quick View latest run.
4. Confirm by-time breakdown and source scope block are visible.
5. Click Revert Scenario Effects.
6. Click Verify Revert Balance.

Expected output:
- Run completes with run id.
- Scope keys include district/state/neighbor_state/national.
- Revert verify shows PASS-like result with net_total = 0.

Note from latest verified run:
- by_time_rows: 4
- incident_count: 1
- verify_revert_balance net_total: 0.0

---

### Case 7 (District) - Request Form Happy Path Batch Submit

Dashboard: District -> District Request

Inputs (Add Resource Request panel):
- Resource: R7 (or any available)
- Quantity: 10
- Time: 1
- Priority: 3
- Urgency: Medium
- Confidence: 1
- Source: human

Actions:
1. Click Add to Request Batch.
2. Click Submit All Requests.

Expected output:
- Success message: Submitted X requests in one batch.
- Request Status Log refreshes with new row(s).

---

### Case 8 (District) - Validation Guard (Huge Quantity)

Dashboard: District -> District Request

Inputs:
- Resource: choose any valid resource
- Quantity: 999999999
- Time: 1
- Confidence: 1

Actions:
1. Add to batch.
2. Submit All Requests.

Expected output:
- Validation error is shown in red.
- Form remains interactive (no crash, no freeze).

---

### Case 9 (State) - Escalate District Request to National

Dashboard: State -> State Requests

Inputs:
- Filter district: 603 (optional)
- Filter status: pending (or unmet/partial)

Actions:
1. Locate a District Request card where status is not escalated_national.
2. Click Escalate to National.

Expected output:
- Button enters Escalating... briefly.
- Row status transitions to escalated_national.
- Escalation Candidates count decreases / Already Escalated increases.

---

### Case 10 (National) - Resolve Escalation (Allocate / Partial / Mark Unmet)

Dashboard: National -> National Requests

Inputs:
- Filter state: 33 (optional)
- Filter district: 603 (optional)

Actions:
1. Open an Escalated Demand card.
2. Demonstrate one action:
   - Allocate (full)
   - Partial (half)
   - Mark Unmet

Expected output:
- Request resolves and leaves active escalated list.
- Group summary and card counts refresh.
- National stock/pool figures remain visible for auditability.

## 4) Demo Order Recommendation (Tomorrow)

Use this order for a clean narrative:
1. Case 1
2. Case 2
3. Case 3
4. Case 4
5. Case 5
6. Case 6
7. Case 7
8. Case 8
9. Case 9
10. Case 10

This order demonstrates: scenario setup -> controlled demand generation -> stock controls -> solver cycle -> rollback integrity -> district intake -> state escalation -> national resolution.

## 5) Quick Fallback Notes During Live Demo

- If a specific resource id is not visible in dropdown, pick any available resource and keep same quantities.
- If no state request is immediately pending, submit Case 7 first, wait 3-10 seconds for refresh, then do Case 9.
- If no national escalations are visible, trigger Case 9 first, then perform Case 10.
- If system is busy, wait for the working overlay to clear before next action.

## 6) Reviewer Talking Points

- Admin flow validated end-to-end with preview/apply/run/revert/verify (18/18 pass in fresh smoke).
- Cross-role APIs validated with successful auth and endpoint responses.
- Dashboards support both positive path and guarded negative path (validation + status lifecycle).
- Revert verification gives operational assurance for scenario-side effects.

## 7) Why These Outputs Are Correct (Input -> Output Logic)

### Case 1 (Create Scenario)

- Why it should work:
  - Create Scenario submits a POST to admin scenarios endpoint with name.
  - Backend returns a new scenario id and default empty counts.
- Why expected output is right:
  - New scenario must appear in dropdown because scenario list is reloaded after create.
  - Status line must show initial counts because no demand/stock has been added yet.

### Case 2 (Manual Demand Batch)

- Why it should work:
  - Selected districts x resources x time horizon generates batch rows.
  - Add Demand Batch posts those rows into scenario demand table.
- Why expected output is right:
  - Persisted demand rows increase because valid rows are inserted.
  - Lifecycle changes draft -> ready because ready state requires persisted demand > 0.

### Case 3 (State Stock Override)

- Why it should work:
  - Valid state_code/resource_id/quantity triggers set-state-stock endpoint.
  - Quantity is positive, so it passes guardrail validation.
- Why expected output is right:
  - No error expected for positive numeric input.
  - State stock row count increases because override row is stored against scenario.

### Case 4 (National Stock Override)

- Why it should work:
  - Valid resource_id and positive quantity triggers set-national-stock endpoint.
  - Form-level validation blocks only non-positive or invalid numbers.
- Why expected output is right:
  - No validation error for valid positive input.
  - National stock row count increments because an override record is added.

### Case 5 (Guided Randomizer Preview)

- Why it should work:
  - Preview does not mutate scenario; it simulates candidate demand rows and metrics.
  - Demand level presets map to increasing intensity ratios.
- Why expected output is right:
  - row_count > 0 is expected when district/resource scope is non-empty.
  - Demand/Supply ratio increases with preset intensity by design of preset mapping.

### Case 6 (Apply -> Run -> Revert -> Verify)

- Why it should work:
  - Apply writes randomized demand rows.
  - Run executes solver and produces allocations/unmet/summary artifacts.
  - Revert posts compensating pool transactions.
  - Verify compares debit and revert totals.
- Why expected output is right:
  - Run id appears because run is persisted.
  - Scope keys are expected in summary schema.
  - net_total = 0 indicates accounting-balanced rollback (correctness criterion).

### Case 7 (District Happy Path Submit)

- Why it should work:
  - Valid request draft fields satisfy quantity/time/confidence validations.
  - Submit All sends batch payload to district request-batch endpoint.
- Why expected output is right:
  - Success toast appears only when API call returns OK.
  - Request log refresh shows inserted requests from backend query refresh cycle.

### Case 8 (District Validation Guard)

- Why it should work:
  - Very large quantity is intentionally beyond configured constraints for resource/request policy.
  - Frontend and/or backend returns validation error for unsafe input.
- Why expected output is right:
  - Error is shown in red by design for failed submit.
  - UI stays interactive because validation should fail gracefully, not crash.

### Case 9 (State Escalation)

- Why it should work:
  - State Requests page allows escalation for eligible statuses (not already escalated_national).
  - Escalate action posts to state escalation endpoint and then reloads requests.
- Why expected output is right:
  - Temporary busy state (Escalating...) is expected while request is in flight.
  - Status becomes escalated_national if backend transition succeeds.
  - Counters update because they are derived from refreshed request statuses.

### Case 10 (National Resolve)

- Why it should work:
  - National resolve action supports allocated/partial/unmet decisions.
  - For allocated/partial, system may move quantity via national pool allocate before marking resolution.
- Why expected output is right:
  - Resolved escalation should leave active escalated list after status transition.
  - Group summaries and card counts refresh from latest backend state.
  - Stock/pool visibility remains, because dashboards expose reserve and pool for audit traceability.

## 8) One-Line Defense You Can Use in Review

- "Each expected result is tied to a specific API/state transition contract: create writes scenario metadata, demand adds rows, run creates summary artifacts, revert enforces accounting balance, and role dashboards reflect status transitions after each mutation." 
