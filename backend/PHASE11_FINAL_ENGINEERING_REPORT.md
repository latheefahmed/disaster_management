## Scope and Method
- This report documents the implemented Phase-11 hardening already merged in backend/frontend, with code-grounded behavior tracing (no assumptions).
- It also documents the active population-based baseline model and district/state/national ratio formulas as implemented in [core_engine/phase4/resources/build_resource_database.py](core_engine/phase4/resources/build_resource_database.py).
- Validation evidence in this file is split into: prior evidence (already executed) and fresh rerun evidence (to be appended after rerun in this session).

## Root Cause Map
- Inventory incompleteness originated from union-based resource discovery in [backend/app/services/kpi_service.py](backend/app/services/kpi_service.py), which omitted resources absent from current stock maps.
- Canonical resource drift originated from mixed IDs and aliases (`water`, `food`, `water_liters`, `food_packets`, `R99`, `T99`) across runtime data and seeds (notably [backend/e2e_seed_data.py](backend/e2e_seed_data.py)).
- Claim/consume/return instability originated from non-canonical IDs and API-side coercions across [backend/app/routers/district.py](backend/app/routers/district.py) and [backend/app/services/action_service.py](backend/app/services/action_service.py).
- KPI canonicality risk originated from missing strict reconciliation against persisted final-demand rows in [backend/app/services/kpi_service.py](backend/app/services/kpi_service.py).

## What Was Added and Changed
- New canonical policy authority: [backend/app/services/canonical_resources.py](backend/app/services/canonical_resources.py).
- Canonical policy propagation:
  - [backend/app/services/resource_policy.py](backend/app/services/resource_policy.py)
  - [backend/app/services/resource_dictionary_service.py](backend/app/services/resource_dictionary_service.py)
  - [backend/app/routers/metadata.py](backend/app/routers/metadata.py)
- DB + migration hardening:
  - [backend/app/database.py](backend/app/database.py)
  - [backend/MIGRATION_SQL.sql](backend/MIGRATION_SQL.sql)
  - [backend/app/models/resource.py](backend/app/models/resource.py) (`unit` support)
- Stock/KPI semantics hardening:
  - [backend/app/services/kpi_service.py](backend/app/services/kpi_service.py)
  - [backend/app/schemas/stock.py](backend/app/schemas/stock.py)
  - [frontend/disaster-frontend/src/components/ResourceInventoryPanel.tsx](frontend/disaster-frontend/src/components/ResourceInventoryPanel.tsx)
  - [frontend/disaster-frontend/src/components/ResourceStockModal.tsx](frontend/disaster-frontend/src/components/ResourceStockModal.tsx)
- Action lifecycle hardening:
  - [backend/app/services/action_service.py](backend/app/services/action_service.py)
  - [backend/app/routers/district.py](backend/app/routers/district.py)
- Validation and request constraints:
  - [backend/app/services/request_service.py](backend/app/services/request_service.py)
  - [frontend/disaster-frontend/src/dashboards/district/DistrictRequest.tsx](frontend/disaster-frontend/src/dashboards/district/DistrictRequest.tsx)
- Seed/test hardening:
  - [backend/e2e_seed_data.py](backend/e2e_seed_data.py)
  - [backend/tests/test_phase11_kpi_stock_regression.py](backend/tests/test_phase11_kpi_stock_regression.py)
  - [frontend/disaster-frontend/e2e/phase11-kpi-stock.spec.ts](frontend/disaster-frontend/e2e/phase11-kpi-stock.spec.ts)

## Canonical Resource Model (Current Implemented)
- Canonical IDs: `R1..R11` in [backend/app/services/canonical_resources.py](backend/app/services/canonical_resources.py).
- Canonical names (current): `food_packets`, `water_liters`, `medical_kits`, `essential_medicines`, `rescue_teams`, `medical_teams`, `volunteers`, `buses`, `trucks`, `boats`, `helicopters`.
- Alias rewrites enforced: `water|water_liters -> R2`, `food|food_packets -> R1`.
- Invalid IDs purged at runtime migration: `R99`, `T99`.
- Quantity policy enforced per resource: `max_quantity_for` + integer-only checks for countable classes.

## Population-Based Baseline Model and Ratios (District/State/Nation)

### Source of truth
- Population source: [core_engine/data/processed/new_data/clean_district_population.csv](core_engine/data/processed/new_data/clean_district_population.csv).
- Baseline generator: [core_engine/phase4/resources/build_resource_database.py](core_engine/phase4/resources/build_resource_database.py).
- Baseline demand feed into backend/solver: [backend/app/services/scenario_runner.py](backend/app/services/scenario_runner.py) via `PHASE3_OUTPUT_PATH/district_resource_demand.csv`.

### District-level formulas (implemented)
- Constants:
  - `WATER_L_PER_PERSON_PER_DAY = 15`
  - `FOOD_RATIONS_PER_PERSON_PER_DAY = 1`
  - `BUFFER_DAYS = 3`
  - `MEDICAL_KITS_PER_1000 = 1.0`
- District deterministic/parametric baseline:
  - $R2\_water = 15 \times population \times 3$
  - $R1\_food = 1 \times population \times 3$
  - $R3\_medical\_kits \sim \text{Poisson}(population/1000)$
  - $R4\_essential\_medicines = 5 \times R3$
  - Personnel/logistics resources are generated from population-scaled Poisson/normal proxies (see resource rows around generation loop in [core_engine/phase4/resources/build_resource_database.py](core_engine/phase4/resources/build_resource_database.py)).

### State and national aggregation ratios (implemented)
- State stock from district aggregate:
  - `STATE_MOBILIZATION_RATIO = 0.40`
  - $state\_stock(resource) = 0.40 \times \sum district\_stock(resource)$
- National stock from state aggregate:
  - `NATIONAL_MOBILIZATION_RATIO = 0.30`
  - $national\_stock(resource) = 0.30 \times \sum state\_stock(resource)$
- Combined district->state->national scaling:
  - $national\_stock \approx 0.12 \times \sum district\_stock$ (because $0.40 \times 0.30 = 0.12$).

### Runtime stock exposure semantics (API)
- District/state/national stock APIs expose:
  - `district_stock`, `state_stock`, `national_stock`, `in_transit`, `available_stock`
- Availability equation:
  - $available\_stock = district\_stock + state\_stock + national\_stock - in\_transit$
- Implemented in [backend/app/services/kpi_service.py](backend/app/services/kpi_service.py), consumed by UI panels.

## KPI Semantics and Invariants
- KPI source is allocation ledger for latest completed run in [backend/app/services/kpi_service.py](backend/app/services/kpi_service.py).
- Definitions:
  - $final\_demand = allocated + unmet$
  - $coverage = allocated/final\_demand$ (0 when denominator is 0)
- Invariant enforcement:
  - If scoped `final_demands` rows exist, enforce persisted sum equality; mismatch raises hard error.

## Request Lifecycle and Visibility
- Live request status refresh is done in [backend/app/services/request_service.py](backend/app/services/request_service.py) by reconciling request slot demand against latest run allocations + unmet.
- Current persisted statuses in [backend/app/models/request.py](backend/app/models/request.py): `pending | solving | allocated | partial | unmet | failed`.
- Requests are not deleted during lifecycle transitions; views are derived through allocation/unmet reconciliation and returned by [backend/app/routers/district.py](backend/app/routers/district.py) `/requests`.

## Claim -> Consume -> Return FSM
- Canonicalized action path in [backend/app/services/action_service.py](backend/app/services/action_service.py):
  - slot status machine: `ALLOCATED -> CLAIMED -> (CONSUMED | RETURNED)` with partial states.
  - hard guards:
    - `claimed <= allocated`
    - `consumed <= claimed`
    - `returned <= claimed - consumed`
  - resource policy checks (consumable/returnable) and per-resource quantity bounds.

## Unmet Demand, Agent Recommendations, and Escalation Wiring
- Unmet rows are represented as `Allocation.is_unmet == True` and surfaced at district/state/national APIs:
  - [backend/app/routers/district.py](backend/app/routers/district.py) `/unmet`
  - [backend/app/routers/state.py](backend/app/routers/state.py) `/unmet`
  - [backend/app/routers/national.py](backend/app/routers/national.py) `/unmet`
- Agent recommendations are generated in scenario runs by [backend/app/services/scenario_runner.py](backend/app/services/scenario_runner.py) (`_write_agent_outputs`) and listed/decided via:
  - [backend/app/routers/admin.py](backend/app/routers/admin.py) `/agent/recommendations`
  - [backend/app/routers/state.py](backend/app/routers/state.py) `/agent/recommendations`

## Historical Run Integrity
- Each run has unique row identity (`SolverRun.id`) with `status/mode/timestamps` and associated artifacts.
- Run history browsing is exposed via admin scenario endpoints in [backend/app/routers/admin.py](backend/app/routers/admin.py):
  - `/scenarios/{scenario_id}/runs`
  - `/scenarios/{scenario_id}/runs/{run_id}/summary`
- Lineage-style summaries include allocation/unmet rollups in [backend/app/services/scenario_service.py](backend/app/services/scenario_service.py).

## Current Gap Against Full Master Target
- The current implemented canonical catalog is **11 resources**, not the requested **>=40 resource-complete catalog**.
- Population baseline currently exists for the 11 canonical resources (phase4 generator), not the full requested multi-category catalog (food-water-medical-capacity-SAR-transport-power-comms-sanitation-logistics).
- Request lifecycle enum currently uses `pending/solving/allocated/partial/unmet/...`, not the full explicit chain `CREATED -> VALIDATED -> MERGED -> SENT_TO_SOLVER -> ALLOCATED/PARTIAL/UNMET -> ESCALATED`.
- Therefore, this phase is a hardened canonical-11 implementation, not yet full resource-complete architecture.

## Tests and Evidence (Fresh Rerun in Current Session)
- Backend targeted regression:
  - `python -m pytest tests/test_phase11_kpi_stock_regression.py -q` -> `9 passed`.
- Frontend unit tests:
  - `npm test -- --runInBand` -> `8 files passed, 51 tests passed`.
- Frontend E2E target spec:
  - `npx playwright test e2e/phase11-kpi-stock.spec.ts --reporter=list` -> `6 passed, 1 skipped, 0 failed`.
- Live API checks:
  - `/metadata/resources` -> 11 canonical resources (`R1..R11`)
  - `/district/stock` -> 11 rows including `in_transit` and `available_stock`.

## Final Verdict
## Final Verdict
- SYSTEM STATUS: **NOT STABLE**
- Reason:
  - Canonical-11 backend hardening is functionally in place and backed by green targeted backend/unit tests.
  - E2E still contains environment-dependent skips (improved from 3 skips to 1 skip on rerun, but not zero-skip).
  - Full master objective (>=40 canonical resources + explicit end-to-end lifecycle model + zero-skip E2E) remains partially unmet.