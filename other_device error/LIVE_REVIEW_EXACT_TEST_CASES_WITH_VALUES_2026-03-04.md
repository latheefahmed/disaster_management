# Live Review – Exact Test Cases with Real Values

Date: 2026-03-04  
Source of values: current `backend/backend.db` snapshot (latest completed run `1095`) + current stock refill balances.

---

## 1) Exact Baseline Values (from your DB)

### Dataset A (District + State escalation)
- District: `603`
- State: `33`
- Resource: `R39`
- Time: `30`
- District stock (`D`): `2,282,956,800`
- State stock (`S`): `70,568,106`
- District + State capacity: `2,353,524,906`

### Dataset B (District + National escalation)
- District: `189`
- State: `9`
- Resource: `R52`
- Time: `4`
- District stock (`D`): `209,949,460`
- National stock (`N`): `393,316,176`
- District + National capacity: `603,265,636`

---

## 2) District Role – 5 Exact Test Cases

Login: `district_603` / `district123` (for A cases), `district_189` / `district123` (for B case)

## D-01 District-only fulfillment (A)
- Execute request:
  - district: `603`
  - resource: `R39`
  - time: `30`
  - quantity: `500,000,000`
- Why this works: `500,000,000 < D (2,282,956,800)`
- Expected:
  - No escalation
  - Unmet `0`

## D-02 District + State escalation (A)
- Execute request:
  - district: `603`, resource: `R39`, time: `30`, quantity: `2,300,000,000`
- Why this works: `D < 2,300,000,000 < D+S`
- Expected:
  - State escalation occurs
  - Unmet `0`

## D-03 State-heavy near-capacity (A)
- Execute request:
  - district: `603`, resource: `R39`, time: `30`, quantity: `2,350,000,000`
- Why this works: very close to `D+S` (= `2,353,524,906`)
- Expected:
  - State escalation occurs heavily
  - Unmet `0` or tiny rounding residue

## D-04 Forced unmet after state exhaustion (A)
- Execute request:
  - district: `603`, resource: `R39`, time: `30`, quantity: `2,500,000,000`
- Why this works: exceeds `D+S` by `146,475,094`
- Expected:
  - State escalation occurs
  - Unmet around `146,475,094` (approx)

## D-05 District + National escalation path (B)
- Execute request:
  - district: `189`, resource: `R52`, time: `4`, quantity: `500,000,000`
- Why this works: exceeds district `D=209,949,460`, below `D+N=603,265,636`
- Expected:
  - National level participates
  - Unmet `0`

---

## 3) State Role – 5 Exact Test Cases

Login: `state_33` / `state123`

## S-01 View escalated request from D-02
- Precondition: execute D-02
- Check: State requests/escalations list includes district `603`, `R39`, time `30`, qty `2,300,000,000`
- Expected: state queue visibility confirmed

## S-02 Allocate from state pool for D-02
- Precondition: D-02 exists
- Execute: state pool allocation for `R39`, time `30`
- Expected: request resolves with unmet `0`

## S-03 High pressure allocation for D-03
- Precondition: D-03 exists
- Execute: process `2,350,000,000` demand
- Expected: state contributes close to full available `S=70,568,106`

## S-04 Failure boundary / unmet proof via D-04
- Precondition: D-04 exists
- Execute: process request from state side
- Expected: state capacity fully consumed; unmet remains (~`146,475,094`)

## S-05 Refill then replay D-04
- Execute refill before replay:
  - state: `33`
  - resource: `R39`
  - refill quantity: `150,000,000`
- Replay D-04 (`2,500,000,000`)
- Expected:
  - unmet should drop substantially versus previous D-04 run

---

## 4) National Role – 5 Exact Test Cases

Login: `national_admin` / `national123`

## N-01 View escalated request from D-05
- Precondition: execute D-05
- Expected: `R52` escalation appears in national queue

## N-02 National allocation success (B)
- Execute quantity: same D-05 (`500,000,000`)
- Expected:
  - national contributes
  - unmet `0`

## N-03 Force unmet beyond national capacity (B)
- Execute request:
  - district `189`, resource `R52`, time `4`, quantity `700,000,000`
- Why this works: exceeds `D+N=603,265,636` by `96,734,364`
- Expected:
  - national exhausted for this path
  - unmet around `96,734,364` (approx)

## N-04 National refill recovery
- Refill national stock:
  - resource `R52`, quantity `150,000,000`
- Replay N-03 (`700,000,000`)
- Expected:
  - unmet reduces or becomes zero depending on prior consumption

## N-05 Provenance check
- Open run summary/allocation details after N-02/N-03
- Expected:
  - `source_level` shows `national` for national-allocated segments

---

## 5) Admin Role – 5 Exact Test Cases

Login: `admin` / `admin123`

## A-01 Create scenario with exact demand row (A)
- Create scenario `REVIEW_EXACT_A`
- Add demand row:
  - district `603`, state `33`, resource `R39`, time `30`, quantity `2,300,000,000`
- Run scenario
- Expected: state escalation, unmet `0`

## A-02 Unmet scenario row (A)
- Add demand row in same/new scenario:
  - district `603`, state `33`, resource `R39`, time `30`, quantity `2,500,000,000`
- Run scenario
- Expected: unmet around `146,475,094`

## A-03 National path scenario (B)
- Add demand row:
  - district `189`, state `9`, resource `R52`, time `4`, quantity `500,000,000`
- Run scenario
- Expected: national allocation appears

## A-04 Full stress with unmet (B)
- Add demand row:
  - district `189`, state `9`, resource `R52`, time `4`, quantity `700,000,000`
- Run scenario
- Expected: unmet around `96,734,364`

## A-05 Stock override variant (exact override values)
- Set state stock override:
  - state `33`, resource `R39`, quantity `70,568,106`
- Set national stock override:
  - resource `R52`, quantity `393,316,176`
- Re-run A-02/A-04 variants and compare
- Expected: clear before/after escalation and unmet change

---

## 6) Fast Execution API Payloads (copy-ready)

### District request payload
`POST /district/request`
```json
{
  "resource_id": "R39",
  "time": 30,
  "quantity": 2300000000,
  "priority": 5,
  "urgency": 5,
  "confidence": 1.0,
  "source": "human"
}
```

### Admin add-demand payload
`POST /admin/scenarios/{scenario_id}/add-demand`
```json
{
  "district_code": "603",
  "state_code": "33",
  "resource_id": "R39",
  "time": 30,
  "quantity": 2500000000
}
```

### Admin state stock override
`POST /admin/scenarios/{scenario_id}/set-state-stock`
```json
{
  "state_code": "33",
  "resource_id": "R39",
  "quantity": 70568106
}
```

### Admin national stock override
`POST /admin/scenarios/{scenario_id}/set-national-stock`
```json
{
  "resource_id": "R52",
  "quantity": 393316176
}
```

---

## 7) Note for review panel
- These values are extracted from your **current local DB** and are not placeholders.
- If stock changes before tomorrow, re-run extraction script and update this file:
  - `backend/tmp_find_overlap_any_run.py`
  - `backend/tmp_extract_exact_values_with_refills.py`
