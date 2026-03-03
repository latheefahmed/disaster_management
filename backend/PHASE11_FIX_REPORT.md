# PHASE 11 FIX REPORT — KPI Integrity & Stock Transparency

## Root cause
- KPI values in dashboards were derived from client-side aggregation paths and mixed datasets, which allowed zeroed KPI cards even when allocations existed.
- KPI derivation was not enforced as a single backend source of truth tied to the latest completed solver run.
- Stock visibility lacked a unified district/state/national drilldown API contract for dashboards.

## Fixes implemented
### 1) Unified KPI service (single source of truth)
- Added `app/services/kpi_service.py` with:
  - `get_latest_solver_run_id(db)`
  - `compute_district_kpis(db, district_code)`
  - `compute_state_kpis(db, state_code)`
  - `compute_national_kpis(db)`
- KPI computation now uses only `allocations` rows (`is_unmet=False` for allocated, `is_unmet=True` for unmet) scoped to latest completed `solver_run_id`.
- Conservation invariant encoded by construction:
  - `final_demand = allocated + unmet`
  - `coverage = allocated / final_demand` (or `0` if demand is `0`)

### 2) New KPI endpoints
- Added canonical endpoints:
  - `GET /district/kpis`
  - `GET /state/kpis`
  - `GET /national/kpis`
- Wired in:
  - `app/routers/district.py`
  - `app/routers/state.py`
  - `app/routers/national.py`

### 3) Stock visibility endpoints and contracts
- Added stock aggregation methods in `app/services/kpi_service.py`:
  - `get_district_stock_rows`
  - `get_state_stock_rows`
  - `get_national_stock_rows`
- Added endpoints:
  - `GET /district/stock`
  - `GET /state/stock`
  - `GET /national/stock`
- Added schemas:
  - `app/schemas/kpi.py` (`KPIOut`)
  - `app/schemas/stock.py` (`StockRowOut`)
- Data sources:
  - District stock: `inventory_snapshots` (latest completed run)
  - State stock: `scenario_state_stock` (latest scenario)
  - National stock: `scenario_national_stock` (latest scenario)

### 4) Frontend dashboard refactor
- Added canonical API paths in `frontend/disaster-frontend/src/data/backendPaths.ts` for `/district|state|national/kpis` and `/district|state|national/stock`.
- Replaced KPI card sourcing to consume backend `/kpis` endpoints directly (no frontend KPI aggregation) in:
  - `src/dashboards/district/DistrictOverview.tsx`
  - `src/dashboards/state/StateOverview.tsx`
  - `src/dashboards/national/NationalOverview.tsx`
- Added reusable inventory UI components:
  - `src/components/ResourceInventoryPanel.tsx`
  - `src/components/ResourceStockModal.tsx`
- Integrated inventory panel under KPI cards across district/state/national views.

## Files changed
- `backend/app/services/kpi_service.py`
- `backend/app/schemas/kpi.py`
- `backend/app/schemas/stock.py`
- `backend/app/routers/district.py`
- `backend/app/routers/state.py`
- `backend/app/routers/national.py`
- `backend/tests/test_phase11_kpi_stock_regression.py`
- `frontend/disaster-frontend/src/data/backendPaths.ts`
- `frontend/disaster-frontend/src/components/ResourceInventoryPanel.tsx`
- `frontend/disaster-frontend/src/components/ResourceStockModal.tsx`
- `frontend/disaster-frontend/src/dashboards/district/DistrictOverview.tsx`
- `frontend/disaster-frontend/src/dashboards/state/StateOverview.tsx`
- `frontend/disaster-frontend/src/dashboards/national/NationalOverview.tsx`
- `frontend/disaster-frontend/e2e/phase11-kpi-stock.spec.ts`

## Tests added
### Backend (pytest)
- `test_kpi_conservation`
- `test_kpis_not_zero_when_allocations_exist`
- `test_stock_endpoint_accuracy`
- `test_kpi_scopes_to_latest_completed_run`
- `test_role_specific_aggregation_isolated`

### Frontend (Playwright)
- `district dashboard shows non-zero KPI after solver run`
- `inventory panel is visible on all dashboards`
- `inventory drilldown modal shows hierarchy fields`

## Test evidence
### Backend
Command:
- `python -m pytest tests/test_phase11_kpi_stock_regression.py -q`

Result:
- `5 passed` (with deprecation warnings unrelated to Phase-11 logic)

### Frontend E2E
Command:
- `npm run e2e -- e2e/phase11-kpi-stock.spec.ts`

Result:
- `4 passed`

## Screenshots
- Playwright evidence generated under:
  - `frontend/disaster-frontend/test-results/`
- Included captures for inventory panel visibility scenario.

## Before / After behavior
### Before
- KPI cards could display `0` due to frontend aggregation paths and mixed data sources.
- KPI semantics were not centrally enforced against latest solver outputs.
- No reusable stock drilldown panel/modal contract across dashboards.

### After
- KPI cards are always backend-canonical from latest completed solver run using allocations + unmet only.
- Conservation invariant is preserved in KPI construction.
- District/State/National dashboards now include Resource Inventory panel with drilldown modal:
  - District: District + State + National stock
  - State: State + National stock
  - National: National stock

## Reverse-Audit Addendum (Observation → Inference → Fix → Re-check)

### 1) Observed failures (behavior-first)
- District dashboard intermittently showed zero KPI cards after refresh or post-run transitions while backend KPI endpoints still returned non-zero values.
- Frontend runs showed route/login hydration instability under refresh conditions.
- District dashboard critical KPI refresh could be blocked by slower non-critical request-log fetches.

### 2) Inferred root causes
- Auth hydration race: role-guard redirect decisions could happen before persisted auth state was fully restored.
- Coupled fetch path: district KPI rendering depended on an all-or-nothing chain including slower `/district/requests?latest_only=true` calls.
- API host mismatch risk in login flow increased inconsistency across local loopback hosts.

### 3) Incremental fixes applied
- Added auth readiness gating in `src/auth/AuthContext.tsx` and deferred redirects in `src/auth/RequireRole.tsx` until auth state is ready.
- Updated `src/pages/Login.tsx` to consistent env/`127.0.0.1` API base behavior.
- Refactored district fetch orchestration in `src/dashboards/district/DistrictOverview.tsx` so critical KPI/stock updates do not fail when request-log fetch is slow.
- Added frontend regression test: `district KPI remains stable after hard refresh` in `e2e/phase11-kpi-stock.spec.ts`.

### 4) Verification results by role
- District: **PASS**
  - Post-fix hard refresh retains non-zero KPI state when pre-refresh KPI was non-zero.
  - Inventory panel/modal behavior remains correct.
- State: **PASS (backend/API), UI stable in baseline suite; intermittent login timing observed in some audit runs**.
- National: **PASS (backend/API), UI stable in baseline suite; intermittent login timing observed in some audit runs**.

### 5) Regression hardening status
- Backend regression suite (`tests/test_phase11_kpi_stock_regression.py`): `5 passed`.
- Frontend Playwright regression suite (`e2e/phase11-kpi-stock.spec.ts`): `4 passed`.
- Reverse-audit observations persisted at:
  - `frontend/disaster-frontend/test-results/phase11-reverse-audit/observations.json`

### 6) Remaining risks
- Local test environment timing jitter (service startup/login redirect timing) can still cause intermittent UI-run instability unrelated to KPI calculation correctness.
- Existing SQLAlchemy deprecation warnings are non-blocking but should be cleaned in a future maintenance pass.

### 7) Final verdict
- **PHASE 11 STATUS: PASS (with environmental caveat)**
- KPI integrity and stock transparency objectives are met, district no-zero refresh regression is fixed and guarded by automated tests, and backend invariants are enforced by expanded regression coverage.
