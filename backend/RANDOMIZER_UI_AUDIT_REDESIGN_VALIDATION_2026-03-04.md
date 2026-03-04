# Scenario Randomizer & Simulation UI Audit / Redesign / Validation (2026-03-04)

## Scope & Constraints Applied
- Solver behavior was not modified.
- Allocation optimization constraints were not modified.
- Demand values continue to originate only from scenario randomizer/manual demand input paths.
- Changes were limited to scenario randomizer generation, admin UI logic, and observability surfaces.

## Part 1 — Randomizer Architecture Audit (Findings)

### Previous behavior (before patch)
- Demand generation used broad preset multiplier bands (`very_low`..`extreme`) and baseline-driven random multipliers.
- Randomizer could sample districts/resources using `district_count` / `resource_count` when explicit selector lists were empty.
- Preview metrics emphasized baseline ratio and row counts, but did not directly present the requested demand/supply diagnostics.
- Supply awareness existed in stock-aware mode, but state/national pools were not represented with the structured 7-level intensity ladder.

### Gaps identified
- UI/backend mismatch: randomizer accepted count-based sampling while hierarchical selector suggested explicit scope control.
- Intensity semantics were not aligned to the requested fixed supply-ratio ladder.
- Preview diagnostics lacked explicit `total_supply`, `total_generated_demand`, `demand/supply ratio`, and `expected shortage`.
- Allocation provenance visibility lacked explicit per-row `source_level` in summary details.

## Part 2 — Demand Intensity Model Implemented

Implemented levels and ratios:
- `extremely_low` → `0.20 × supply`
- `low` → `0.40 × supply`
- `medium_low` → `0.70 × supply`
- `medium` → `1.00 × supply`
- `medium_high` → `1.25 × supply`
- `high` → `1.50 × supply`
- `extremely_high` → `1.79 × supply`

Compatibility aliases retained:
- `very_low` → `extremely_low`
- `extreme` → `extremely_high`

Supply used by randomizer:
- District stock + state stock + national stock (within selected district/resource scope).
- Shared state/national pools are distributed proportionally across selected district-resource pairs to avoid pool over-counting.

Demand generation algorithm:
1. Compute total available supply for selected scope.
2. Compute ratio target demand (`target = ratio × supply`).
3. Distribute target demand across selected district-resource pairs with deterministic seeded randomness.
4. Distribute each pair target across time slots with deterministic seeded randomness.
5. Reconcile cent-level rounding drift so generated totals match target demand.

## Part 3 — Randomizer UI Fixes

Implemented:
- Guided randomizer controls remain disabled when Manual mode is active.
- Preview/Apply buttons are disabled in Manual mode.
- Randomizer scope is now selector-only (district/resource explicit selections required).
- Count-based randomizer controls (`district_count`, `resource_count`) removed from effective payload usage and UI flow.
- Numeric input edit bug fixed for key controls by allowing temporary empty string states before parsing:
  - time horizon
  - base demand
  - demand multiplier
  - manual priority
  - manual urgency
  - manual time index
  - random seed

## Part 4 — Randomizer Preview Improvements

Preview now includes:
- `total_available_supply`
- `total_generated_demand`
- `demand_supply_ratio`
- `expected_shortage_estimate`
- selected district list
- selected resource list
- total demand rows
- existing diagnostics (`stock_backed_rows`, `zero_stock_rows`, avg priority/time_index, warnings)

## Part 5 — Allocation Provenance Visibility

Backend summary enhancements:
- `allocation_details` now include `source_level` normalized to `{district, state, national}`.
- summary flags added:
  - `used_state_stock`
  - `used_national_stock`

Admin dashboard enhancements:
- Run details show `used_state_stock` / `used_national_stock` flags.
- Run details render allocation provenance table with:
  - `resource_id`
  - `district_code`
  - `time`
  - `allocated_quantity`
  - `source_level`

## Neighbor Escalation / Manual Aid Auto-Approval

- Live escalation path has neighbor auto-accept enabled by default via `AUTO_ESCALATION_NEIGHBOR_AUTO_ACCEPT=true` fallback.
- Scenario run summary escalation visibility was improved to backfill neighbor accepted quantity/accepted marker when neighbor allocations exist but explicit audit event rows are absent.
- Scenario mode remains labeled distinctly from live auto-chain mode in `escalation_status.mode`.

## Part 6 — Testing Results

### A) 15-case randomizer-only sweep
- Report: `RANDOMIZER_SWEEP_15_CASE_REPORT_2026-03-04.md`
- Result: 15/15 pass.

### B) 15-case stress + escalation sweep
- Report: `RANDOMIZER_STRESS_ESCALATION_15_CASE_REPORT_2026-03-04.md`
- Result: 15/15 pass, escalation signaled in 15/15 cases.

### C) 7-level intensity ladder certification
- Report: `RANDOMIZER_INTENSITY_LADDER_VALIDATION_2026-03-04.md`
- Result: 7/7 pass.
- Level expectations validated:
  - extremely_low → surplus behavior
  - medium → balanced service
  - medium_high → state pool usage
  - high → national pool usage
  - extremely_high → unmet appears
- Deterministic preview checks with fixed seed passed for all levels.

## Part 7 — Non-Modification Guarantees
- Solver algorithm not changed.
- Solver allocation numbers are not post-processed or manipulated.
- Optimization constraints untouched.

## Part 8 — Changed Files
- `backend/app/services/scenario_control_service.py`
- `backend/app/services/scenario_service.py`
- `frontend/disaster-frontend/src/dashboards/admin/AdminOverview.tsx`
- Validation utilities:
  - `backend/tmp_intensity_ladder_validation.py`

## Stability Note
- Updated backend was verified on default endpoint `http://127.0.0.1:8000`.
- UI/TS and backend static checks on modified files report no errors.
