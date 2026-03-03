# Structural Discovery Audit (Pre-Testing)

## Scope and Method
- Mode: source-driven, read-only structural discovery (no destructive or load testing).
- Backend scanned: `backend/app/main.py`, routers, auth/deps/security, core lifecycle services (`request_service.py`, `action_service.py`, `mutual_aid_service.py`).
- Frontend scanned: route/auth/navigation wiring, role dashboards, shared data-table/stock/refill components, API path registry.
- Output objective: full map of auth, routes, endpoint contracts, lifecycle/escalation behavior, risk checkpoints, and credential coverage needs.

## Authentication and Session Topology
### Backend auth
- `POST /auth/login` authenticates with username/password and returns token + role + state/district context.
- Tokens are opaque hex strings (`secrets.token_hex(32)`), persisted in both in-memory store and SQLite table `auth_tokens`.
- Role gating is enforced via `require_role([...])` from bearer payload.
- No explicit token expiry or refresh endpoint is implemented.

### Frontend auth
- Auth state is persisted in `localStorage` keys: `user`, `token`.
- `RequireRole` guards all non-login routes and redirects unauthorized users to `/login`.
- API client injects bearer token on every request from `localStorage`.
- No global 401 recovery/logout flow exists.

## Role Navigation Tree
- Public: `/login`
- District role:
  - `/district`
  - `/district/request`
- State role:
  - `/state`
  - `/state/requests`
- National role:
  - `/national`
  - `/national/requests`
- Admin role:
  - `/admin`
  - `/admin/scenarios/:scenarioId/runs/:runId`

## UI Structural Map (Tabs, Filters, Actions)
### District
- Overview tabs: Requests, Allocations, Upstream Supply, Unmet, Resource Stocks, Refill Resources, Agent Recommendations, Run History.
- Requests sub-tabs: Pending, Allocated, Partial, Unmet, Escalated.
- Main actions: request navigation, run solver, export CSV, demand mode switch, claim/consume/return per allocation slot.
- Polling cadence: ~4s (`DistrictOverview`), ~3s (`DistrictRequest`).

### State
- Overview tabs: District Requests, Mutual Aid Outgoing/Incoming, State Stock, Refill Resources, Agent Recommendations, Run History.
- State Requests page: district/resource/status filters, clear, grouped summary, escalation-to-national action.
- Polling cadence: ~4s (`StateOverview`), ~3s (`StateRequests`).

### National
- Overview tabs: State Summaries, National Stock, Refill Resources, Inter-State Transfers, Agent Recommendations, Run History.
- National Requests page: state/district/resource filters and escalation decision actions (Allocate / Partial / Mark Unmet).
- Polling cadence: ~5s (`NationalOverview`), ~4s (`NationalRequests`).

### Admin
- Top tabs: System Health, Solver Runs, Neural Controller Status, Agent Findings, Audit Logs.
- Scenario controls: create scenario, hierarchical state/district selection, resource multi-select, scenario type, horizon/demand controls, stock overrides, simulation trigger.
- Run details page: resource/district filters and CSV exports for breakdown/allocation/unmet.

### Shared table and stock components
- `OpsDataTable`: global search, per-column filters, sortable headers, pagination, raw JSON row viewer.
- `ResourceStockTabs`: scope switcher (district/state/national), resource search, scoped totals.
- `ResourceRefillPanel`: resource selector + quantity + note -> immediate refill POST.

## Request Lifecycle and Solver Binding
- Request creation (`/district/request`, `/district/request-batch`) normalizes resource/time/quantity, merges pending slot duplicates, persists prediction metadata, then starts live solver asynchronously.
- Lifecycle refresh (`_refresh_request_statuses_for_latest_live_run`) maps slot-level allocation/unmet back to requests and updates status/lifecycle fields (`pending/solving/allocated/partial/unmet/escalated/failed`).
- Latest-run dashboard binding uses completed runs with demand/allocation signal to avoid empty-run artifacts.
- `latest_only=true` request view excludes `solving` rows and binds to latest completed live run when available.

## Escalation and Mutual Aid Structural Flow
### District -> mutual aid market
1. District can open aid request (`/district/mutual-aid/request`).
2. Other states see open market (`/state/mutual-aid/market`) and submit offers.
3. Requesting state responds to offers (`accepted/rejected`), accepted offers create confirmed `StateTransfer` records.

### State -> national escalation
1. State escalates request (`POST /state/escalations/{request_id}`).
2. National resolves (`POST /national/escalations/{request_id}/resolve`).
3. Optional pool allocation path uses `/national/pool/allocate` before/with resolve decision.

### Pool and returns
- Returns from districts route to district stock refill or to origin state/national pool depending on source scope and provenance resolution.
- State/national pool allocations write negative pool transactions and are bounded by available balance.

## Endpoint Catalog
Complete endpoint inventory with method, role, request shape, response, and side-effect classification is provided in:
- `backend/STRUCTURAL_DISCOVERY_SYSTEM_MAP.json` (`endpoint_catalog`)

## Risk Checkpoint Mapping
- Negative quantity controls: partially guarded (input mins + backend validation), but delta tables intentionally show negatives for outflow transactions.
- Status filter mismatch risk: present (UI status literals can hide unrecognized backend statuses).
- Cross-role cache invalidation: present (polling-based coherence; no push/event invalidation).
- Resource canonicalization: guarded in backend service normalization; weaker in free-text admin override fields.
- Delay/freshness lag: expected behavior due to 3–5s polling and client-time freshness labels.
- Zero-final-demand run binding: guarded by completed-run-with-signal selection logic.

## Ambiguities and Inconsistencies
1. Login page role/state/district selectors are UI-only; backend role derives from credentials and selectors are not sent in login payload.
2. No explicit token expiry model despite some generic “expired token” error wording.
3. `StateRequests` uses `/state/escalations` as source while page labels suggest broader request scope.
4. Admin Audit tab is browser-local event log, not backend audit-log stream.
5. Several admin/meta endpoints use untyped `dict` payloads rather than strict schema contracts.

## Credential Coverage Requirements (for next test phase)
- Required baseline users:
  - District account with valid `district_code` + `state_code`
  - State account with valid `state_code`
  - National account
  - Admin account
- Multi-actor flow validation needs:
  - At least two state accounts (offer/accept across states)
  - Districts from same and different states
- Data readiness needs:
  - Populated metadata/resources
  - Non-zero stock and refill paths
  - Pending/escalated requests present for state/national request pages

## Artifacts Produced
- `backend/STRUCTURAL_DISCOVERY_AUDIT.md` (human-readable audit)
- `backend/STRUCTURAL_DISCOVERY_SYSTEM_MAP.json` (structured map + endpoint contracts)
