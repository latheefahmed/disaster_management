# Live Project Review Test Cases (District / State / National / Admin)

Date: 2026-03-04  
Purpose: Live demo pack with escalation variants and executable steps.

---

## 0) Quick Demo Setup (5–10 min)

### A. Start services
- Backend: run your normal backend start command.
- Frontend: run your normal frontend start command.

### B. Login IDs (default bootstrap)
- District: `district_<district_code>` / `district123`
- State: `state_<state_code>` / `state123`
- National: `national_admin` / `national123`
- Admin: `admin` / `admin123`

### C. Pick one demo district/state/resource/time
Use one consistent set across all tests:
- `DISTRICT_A` = your chosen district code (example: `603`)
- `STATE_A` = state code for that district (example: `33`)
- `RESOURCE_X` = one high-volume resource (example: `R6`)
- `TIME_SLOT` = one valid time index (example: `1`)

### D. Capture baseline quantities (for dynamic, reliable demo)
From dashboards/APIs, note:
- `D` = district available stock for `RESOURCE_X`
- `S` = state pool available for `RESOURCE_X`
- `N` = national pool available for `RESOURCE_X`

If you need fixed sample numbers for rehearsal, use:
- `D = 10,000`, `S = 20,000`, `N = 30,000`

### E. Quantity bands (use these in all role tests)
- `Q1 = round(0.30 * D)` → should stay district-only
- `Q2 = round(1.10 * D)` → district + state escalation
- `Q3 = round(D + 0.60 * S)` → heavy state usage, maybe no national
- `Q4 = round(D + S + 0.40 * N)` → reaches national
- `Q5 = round(D + S + N + 0.50 * N)` → forces unmet + full escalation chain

Using sample values (`D=10000, S=20000, N=30000`):
- `Q1=3000`, `Q2=11000`, `Q3=22000`, `Q4=42000`, `Q5=75000`

---

## 1) District Role — 5 Live Test Cases

## D-01 District-only fulfillment (No escalation)
- Input quantity: `Q1`
- Steps:
  1. Login as District (`district_<DISTRICT_A>`).
  2. Create one request for `RESOURCE_X`, `TIME_SLOT`, quantity `Q1`.
  3. Run/submit request processing (district run path).
  4. Open allocations + unmet.
- Expected:
  - Allocation source is district only.
  - State/national usage flags remain false.
  - Unmet = 0.

## D-02 District exhausted, State escalation
- Input quantity: `Q2`
- Steps: same as D-01 with quantity `Q2`.
- Expected:
  - District stock consumed first.
  - Additional allocation from state pool.
  - `used_state_stock = true`, `used_national_stock = false`.
  - Unmet usually 0 if state has enough.

## D-03 High district pressure (state-heavy)
- Input quantity: `Q3`
- Steps: same request flow using `Q3`.
- Expected:
  - District + significant state allocation.
  - National might remain unused if state sufficient.
  - Unmet = 0 or small (depends on your current `S`).

## D-04 National escalation visible from district
- Input quantity: `Q4`
- Steps: submit `Q4`, then check request summary.
- Expected:
  - District + state + national chain visible.
  - `used_state_stock = true`, `used_national_stock = true`.
  - Escalation records present.

## D-05 Full chain + unmet
- Input quantity: `Q5`
- Steps: submit `Q5`, run, check unmet + escalation trail.
- Expected:
  - District and state and national all used.
  - Remaining unmet > 0.
  - This is your strongest “stress escalation” demo case.

---

## 2) State Role — 5 Live Test Cases

## S-01 State sees incoming escalations
- Setup: Execute D-02 first.
- Steps:
  1. Login as State (`state_<STATE_A>`).
  2. Open `requests` / `escalations` view.
- Expected:
  - District request appears in state escalation queue.
  - Request status reflects state-level handling.

## S-02 State pool allocation approval path
- Setup: Use quantity `Q2` or `Q3` request.
- Steps:
  1. In State dashboard, allocate from state pool.
  2. Confirm allocation and refresh summary.
- Expected:
  - State pool decreases by allocated amount.
  - District receives allocation update.
  - No national usage if state suffices.

## S-03 State insufficiency triggers national
- Setup: Use D-04 (`Q4`).
- Steps:
  1. Observe state allocation partial.
  2. Check escalation forwarded upward.
- Expected:
  - State handles partial amount.
  - Remaining demand escalates to national.

## S-04 Mutual-aid offer response variant (if enabled)
- Setup: Use D-05 or a high case where state alone is short.
- Steps:
  1. Open state mutual-aid area.
  2. Accept one offer in first run, reject in second run.
- Expected:
  - Accept variant: reduced unmet / reduced national dependency.
  - Reject variant: higher unmet or more national draw.

## S-05 Refill then resolve
- Setup: before replaying `Q3`/`Q4`, do state stock refill for `RESOURCE_X`.
- Steps:
  1. `state/stock/refill` through UI/API.
  2. Re-run same demand level.
- Expected:
  - Lower escalation depth than before refill.
  - Demonstrates operational recovery behavior.

---

## 3) National Role — 5 Live Test Cases

## N-01 National queue intake check
- Setup: Execute D-04 or S-03 first.
- Steps:
  1. Login as National (`national_admin`).
  2. Open national `requests` / `escalations`.
- Expected:
  - Escalated requests appear with pending quantities.

## N-02 National allocation resolves residual
- Setup: Use `Q4` case with remaining after state.
- Steps:
  1. Allocate from national pool for `RESOURCE_X`.
  2. Refresh district/state summaries.
- Expected:
  - `used_national_stock = true`.
  - Unmet becomes 0 or reduced.

## N-03 National stock insufficient (forced unmet)
- Setup: Use `Q5` where `Q5 > D+S+N`.
- Steps:
  1. Execute request and national allocation.
  2. Open unmet dashboards.
- Expected:
  - National fully utilized.
  - Residual unmet remains visible.

## N-04 National refill recovery
- Setup: After N-03, refill national stock for `RESOURCE_X`.
- Steps:
  1. Run national refill.
  2. Replay same demand.
- Expected:
  - Lower unmet vs before refill.
  - Clear before/after narrative for review panel.

## N-05 Allocation provenance validation
- Setup: Any case using all tiers (prefer `Q4`/`Q5`).
- Steps:
  1. Open scenario run summary/allocation details.
  2. Verify `source_level` entries include district/state/national.
- Expected:
  - Provenance visible per allocation row.
  - Strong traceability demonstration.

---

## 4) Admin Role — 5 Live Test Cases

## A-01 Controlled scenario creation (baseline)
- Steps:
  1. Login as Admin.
  2. Create scenario `REVIEW_BASELINE_<date>`.
  3. Add one demand row for `DISTRICT_A/STATE_A/RESOURCE_X/TIME_SLOT` with `Q1`.
  4. Run scenario in focused mode.
- Expected:
  - Clean baseline result (district-centric).

## A-02 Randomizer preview diagnostics check
- Steps:
  1. Open randomizer for the scenario.
  2. Use selector-only mode with chosen districts/resources.
  3. Preview at `medium_high` and then `extremely_high`.
- Expected:
  - Preview shows supply, generated demand, ratio, expected shortage.
  - `extremely_high` has clearly higher shortage pressure.

## A-03 Randomizer apply + escalation variance
- Steps:
  1. Apply randomizer with fixed seed (record seed).
  2. Run scenario.
  3. Capture run summary incidents/escalations.
- Expected:
  - Deterministic repeatability with same seed.
  - Escalation paths vary by intensity level.

## A-04 State/national override experiment
- Steps:
  1. In same scenario clone, reduce state stock (e.g., -50%).
  2. Keep national stock unchanged.
  3. Re-run same demand.
- Expected:
  - More requests reach national.
  - `used_national_stock` toggles higher.

## A-05 Revert effects + verification
- Steps:
  1. Execute scenario run.
  2. Revert effects using run id.
  3. Verify revert status endpoint/UI panel.
- Expected:
  - Operational data returns to pre-run balance.
  - Excellent governance/control demo.

---

## 5) Variant Matrix (Escalation Coverage)

Use the same demand row and vary only quantity / stock:

- Variant V1: `Q1` → district only.
- Variant V2: `Q2` → district + state.
- Variant V3: `Q4` → district + state + national.
- Variant V4: `Q5` with low `N` → unmet present.
- Variant V5: V4 + mutual aid accept/refill → unmet reduced.

This 5-variant ladder gives a clean escalation story for reviewers.

---

## 6) Live Demo Script (Recommended Order, 12–15 min)

1. **District**: Run D-01 then D-04 (show escalation jump).  
2. **State**: Show S-01 and S-03 (queue + forwarding).  
3. **National**: Show N-02 and N-03 (resolve vs insufficient).  
4. **Admin**: Show A-02 preview diagnostics and A-04 override impact.  
5. End with provenance fields and unmet comparison chart.

---

## 7) Reviewer-friendly Talking Points

- Escalation is policy-driven and tiered (district → state → national).  
- Allocation provenance is auditable per row (`source_level`).  
- `used_state_stock` and `used_national_stock` prove cross-tier involvement.  
- Same scenario with different stock overrides demonstrates resilience planning.  
- Deterministic randomizer seed enables reproducible demos.

---

## 8) Optional Quick API Payload Examples (Admin)

### Create scenario
`POST /admin/scenarios`
```json
{ "name": "REVIEW_DEMO_2026_03_05" }
```

### Add demand row
`POST /admin/scenarios/{scenario_id}/add-demand`
```json
{
  "district_code": "603",
  "state_code": "33",
  "resource_id": "R6",
  "time": 1,
  "quantity": 42000
}
```

### Override state stock
`POST /admin/scenarios/{scenario_id}/set-state-stock`
```json
{
  "state_code": "33",
  "resource_id": "R6",
  "quantity": 20000
}
```

### Override national stock
`POST /admin/scenarios/{scenario_id}/set-national-stock`
```json
{
  "resource_id": "R6",
  "quantity": 30000
}
```

### Run scenario
`POST /admin/scenarios/{scenario_id}/run`
```json
{ "scope_mode": "focused" }
```

---

If you want, I can also generate a second file with a **minute-by-minute speaking script** (exact clicks + what sentence to say per test case).