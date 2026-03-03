## District 603 Stock Validation Report

Date: 2026-02-22

### What was validated
- Backend stock wiring for district/state/national now uses canonical fallback datasets when DB stock tables are sparse.
- Frontend stock UX was moved to dedicated tabs and now renders resource **names** from `/metadata/resources` (not just IDs).
- District, State, and National dashboards now show stock in a dedicated `Resource Stocks` tab.
- State dashboard bug fixed: `State Stock` tab now uses `/state/stock` (not pool rows).
- District dashboard continues to auto-refresh; claim/consume/return actions trigger immediate `fetchData()` refresh.

### Backend data integrity checks (current workspace DB)
- Districts in DB: **720**
- District endpoints returning 56 canonical rows: **720/720**
- Districts with non-zero district stock: **640/720**
- States in DB: **35**
- State endpoints returning 56 canonical rows: **35/35**
- States with non-zero state stock: **35/35**
- National endpoint rows: **56**
- National non-zero resources: **56**

### District 603 verification
- District code found and resolved to State: **33**
- `/district/stock` equivalent service output row count: **56**
- Non-zero district resource rows: **56**

Top 10 resources for District 603 by available stock:

| Resource ID | District Stock | State Stock | National Stock | Available Stock |
|---|---:|---:|---:|---:|
| R6 | 418205880.00 | 7624596888.00 | 38945464373.00 | 46988267141.00 |
| R5 | 139401960.00 | 2541532296.00 | 12981821458.00 | 15662755714.00 |
| R7 | 55760784.00 | 1016612918.00 | 5192728584.00 | 6265102286.00 |
| R1 | 27880392.00 | 508306459.00 | 2596364290.00 | 3132551141.00 |
| R39 | 18586928.00 | 338870973.00 | 1730909529.00 | 2088367430.00 |
| R50 | 16728236.00 | 304983878.00 | 1557818578.00 | 1879530692.00 |
| R40 | 11152156.00 | 203322582.00 | 1038545714.00 | 1253020452.00 |
| R10 | 10687484.00 | 194850808.00 | 995272975.00 | 1200811267.00 |
| R2 | 9758138.00 | 177907263.00 | 908727500.00 | 1096392901.00 |
| R11 | 8828790.00 | 160963710.00 | 822182025.00 | 991974525.00 |

### UI verification evidence
- Frontend test executed: `src/__tests__/districtOverview.test.tsx`
- Result: **passed**
- Verified that stock tab shows resource name (`Rice (kg)`) and backend-provided available quantity (`155`).

### Backend regression evidence
- Test executed: `python -m pytest tests/test_phase11_kpi_stock_regression.py -q`
- Result: **10 passed**
- Includes sparse-stock fallback regression test to prevent dummy/single-resource stock outputs.
