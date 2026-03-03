## Pre-Fix Gap Report (Refill + Allocation Chain)

Date: 2026-02-22

### Scope
This report captures the **pre-fix system behavior gaps** identified while auditing district/state/national stock operations, request-allocation lifecycle, and frontend stock visibility.

### Confirmed Gaps Before Fix

1. **No refill endpoint at any role scope**
   - District had no API to directly refill district stock.
   - State had no API to refill state-level stock.
   - National had no API to refill national stock.
   - Result: users could only indirectly affect stock through returns or scenario files.

2. **Stock depletion not reliably persisted after solver runs**
   - Solver ingest depended on `inventory_t.csv` for inventory snapshots.
   - In observed runs, `inventory_t.csv` was present but empty (header-only).
   - Result: stock values did not consistently go down after allocations, causing stale/incorrect stock perception.

3. **State stock tab wiring mismatch (frontend)**
   - State dashboard `State Stock` tab previously rendered `poolRows` (`/state/pool`) instead of `/state/stock` rows.
   - Result: users saw pool balances instead of canonical stock figures expected for state stock visibility.

4. **Long stock lists reduced operator usability**
   - Raw inventory list was long and difficult to scan.
   - Resource IDs were shown frequently without human-friendly names.
   - Result: slower operations and confusion during incident workflows.

5. **Sparse DB stock snapshots caused misleading values**
   - Latest DB scenario stock could contain partial rows (e.g., isolated values like 90), while canonical datasets were richer.
   - Result: endpoint responses could look dummy/partial if latest DB snapshot was sparse.

6. **No explicit unified refill-to-solver chain**
   - Even when stock-like adjustments were made elsewhere, there was no single guaranteed path ensuring:
     1) refill persisted,
     2) stock endpoint reflected it,
     3) next solver run consumed updated stock,
     4) endpoint reflected post-run depletion.

### Operational Risk From These Gaps
- Resource managers cannot reliably validate that stock actions changed system state.
- Potential mismatch between frontend numbers and backend computation source.
- Decision latency due to poor stock observability and tab wiring issues.
- Increased risk of false partial/unmet interpretations under mutable stock inputs.
