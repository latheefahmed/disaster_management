# SYSTEM_VERIFICATION_REPORT

## Scope
National disaster platform hardening verification for:
- resource flow correctness
- live-run determinism
- dashboard run binding
- provenance + shipment + receipt semantics
- escalation non-blocking behavior

## Time Strategy (Implemented)
Chosen strategy: **Option A**
- Human request time is normalized to `time=0` in request ingestion.
- Delay remains a metadata/output field (`implied_delay_hours`).

Files:
- `backend/app/services/request_service.py`

## Resource Catalog Sanity
### Authoritative source
- Backend metadata endpoint: `GET /metadata/resources`
- Model: `backend/app/models/resource.py`
- Router: `backend/app/routers/metadata.py`

### Fields now exposed for UI catalog
- `resource_id`
- `label`
- `unit`
- plus policy fields (`is_consumable`, `is_returnable`, `must_return_if_claimed`)

Frontend dropdown uses metadata API:
- `frontend/disaster-frontend/src/dashboards/district/DistrictRequest.tsx`

## Merge Layer + Solver Input Guards
### Implemented
- Human+baseline merge remains outer union on keys (`district_code`, `resource_id`, `time`).
- Added pre-solver guard logging:
  - final demand row count
  - distinct resources
  - min/max demand
- Abort condition: `final_demands.count == 0`.
- Included-request guard:
  - if any included request maps to `final_demand_quantity <= 0`, run fails.

Files:
- `backend/app/services/request_service.py`

Sample logged summary:
- `FINAL_DEMAND_INPUT_SUMMARY {'solver_run_id': 8, 'rows': 313280, 'distinct_resource_ids': 11, 'min_quantity': 0.0, 'max_quantity': 2.004152426416878}`

## Allocation Ingest Hardening
### Implemented
- Ingest persists provenance fields:
  - `supply_level`
  - `origin_state_code`
  - `origin_district_code`
- If solver emits non-district allocations but shipment CSV is empty, ingest synthesizes shipment rows.

File:
- `backend/app/engine_bridge/ingest.py`

### DB constraints
Added model constraints:
- `allocated_quantity >= 0`
- `is_unmet IN (0,1)`

File:
- `backend/app/models/allocation.py`

## Shipment + Receipt Confirmation
### Implemented semantics
- For non-district supply, shipment records now exist (parsed or synthesized).
- District receipt workflow endpoint exists:
  - `POST /district/allocations/{id}/confirm`
- Allocation rows carry:
  - `receipt_confirmed`
  - `receipt_time`

Files:
- `backend/app/routers/district.py`
- `backend/app/services/allocation_service.py`
- `backend/app/models/allocation.py`

## Dashboard Binding (Latest Completed Run)
Implemented fallback rule:
- prefer latest completed live run
- if absent, use latest completed scenario run

Evidence (`stability_evidence.json`):
- `selected_when_no_live_completed: { id: 6, mode: scenario }`

Files:
- `backend/app/services/allocation_service.py`
- `backend/app/routers/district.py`
- `backend/app/services/request_service.py`

## Live Run Reliability (Phase M)
### Implemented
- No background daemon threads for live solver.
- Synchronous live execution path retained.
- Exactly one live running run at a time.
- New requests reuse active live run if running; stale running rows (>30m) are failed.

File:
- `backend/app/services/request_service.py`

Current snapshot:
- `RUNNING_LIVE []`

## Numerical Verification (from `stability_evidence.json`)
Generated: `2026-02-21T07:18:22.092927+00:00`

### Case 1 — state pull
- district `228`, resource `R10`
- demand `1.0`, state stock `334.0`, national `0.0`
- final `1.0`, allocated `1.0`, unmet `0.0`
- provenance: `{ state: 1.0 }`
- conservation: ✅

### Case 2 — national pull
- district `496`, resource `R9`
- demand `1.0`, state stock `0.0`, national `4562.0`
- final `1.0`, allocated `1.0`, unmet `0.0`
- provenance: `{ national: 1.0 }`
- conservation: ✅

### Case 3 — full shortage
- district `228`, resource `R10`
- demand `335.0`, state stock `334.0`, national `0.0`
- final `335.0`, allocated `334.0`, unmet `1.0`
- provenance: `{ state: 334.0, unmet: 1.0 }`
- conservation: ✅

### Live determinism
- live run `7` status `completed`
- `final_demands = 35145`
- `allocations = 35145`

### Escalation non-blocking
- request `5` escalated
- rerun `8`
- post-rerun status `allocated`
- slot metrics: final `18.022356`, allocated `18.022356`, unmet `0.0` (conservation ✅)

## SQL Evidence Snapshot
From `run_sql_baseline_diag.py` and `run_running_diag.py`:
- latest completed live run id: `8`
- final_demands count: `35145`
- allocations count: `35145`
- unmet rows: `0`
- running live rows: none (`RUNNING_LIVE []`)

## Frontend Visibility Updates
### District
- Tabs include `Upstream Supply` and allocation provenance badges.
- Allocation rows show source/provenance and receipt state.

### State
- Tab label updated to explicit `Mutual Aid Outgoing / Incoming`.

### National
- Tab label updated to `Inter-State Transfers`.

Files:
- `frontend/disaster-frontend/src/dashboards/district/DistrictOverview.tsx`
- `frontend/disaster-frontend/src/dashboards/district/DistrictRequest.tsx`
- `frontend/disaster-frontend/src/dashboards/state/StateOverview.tsx`
- `frontend/disaster-frontend/src/dashboards/national/NationalOverview.tsx`
- `frontend/disaster-frontend/src/data/districtContracts.ts`

## Residual Risks
- DB check constraints are model-level; existing deployed DBs need migration to enforce at storage layer.
- Screenshot artifacts are not attached in this headless execution context.

## Artifacts
- `backend/stability_evidence.json`
- `backend/SYSTEM_VERIFICATION_REPORT.md`
- `backend/FINAL_STABILITY_REPORT.md`

## Expanded Matrix Verification
Generated: `2026-02-21T07:53:59.243492+00:00`

### Coverage
- districts covered: `7`
- states covered: `2`
- resources checked: `14`
- scenario demand rows inserted: `98`

### Role + Button Flow Results
- district endpoints pass/total: `35/35`
- district action pass/total: `7/7`
- state action pass/total: `4/4`
- national action pass/total: `3/3`
- mutual aid flow pass/total: `2/2`
- frontend wiring checks pass/total: `4/4`

### Notes
- returnable resource used for pool actions: `R10`
- consumable resource used for consume action: `R1`
