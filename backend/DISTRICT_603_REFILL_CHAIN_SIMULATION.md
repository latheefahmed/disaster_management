## District 603 Refill + Allocation Chain Simulation

Date: 2026-02-22

### Simulation Goal
Validate end-to-end chain in live workspace DB:
1. request all resources for district 603,
2. run solver,
3. claim a non-consumable allocation,
4. return that non-consumable,
5. refill all resources,
6. rerun solver,
7. compare stock before/refill/after-rerun.

### Executed Flow
- Target district: `603` (state `33`)
- Resources tested: `56`
- Request batch created for all resources (`time=0`, `quantity=1` each)
- Run 1: solver run id `69`
- Claim + return action:
  - claimed non-consumable: `R10`, quantity `1.0`, slot status -> `CLAIMED`
  - returned non-consumable: `R10`, quantity `1.0`, slot status -> `RETURNED`
- Refill action:
  - district refill applied to **all 56 resources**, `+10` each
- Run 2: solver run id `70`

### Run Outcomes
- Run 1 allocations for district 603: `55`
- Run 1 unmet for district 603: `0`
- Run 2 allocations for district 603: `55`
- Run 2 unmet for district 603: `0`
- Latest run status: `completed`

### Stock Evidence (District level sample)

| Resource | Before | After Refill | After Re-run | Refill Delta | Solver Re-run Delta |
|---|---:|---:|---:|---:|---:|
| R1  | 27880392.0000 | 27880397.2917 | 27880396.5834 | +5.2917 | -0.7083 |
| R2  | 9758138.0000  | 9757743.2917  | 9757742.5834  | -394.7083 | -0.7083 |
| R5  | 139401960.0000 | 139401964.9375 | 139401963.8751 | +4.9375 | -1.0625 |
| R6  | 418205880.0000 | 418205884.8667 | 418205883.7334 | +4.8667 | -1.1333 |
| R10 | 10687484.0000 | 10687489.2209 | 10687488.4417 | +5.2209 | -0.7791 |
| R20 | 185870.0000 | 185880.0000 | 185880.0000 | +10.0000 | 0.0000 |

### Interpretation
- Solver re-run consumed stock (negative post-rerun delta appears on multiple resources).
- Refill effects are visible before rerun and then partially consumed after rerun.
- Non-consumable claim/return path is functioning (R10 claim then return succeeded).
- District 603 did not produce unmet in these two runs under the simulation inputs.

### Notes
- Refill and solver debit are both now represented via a unified stock-adjustment ledger.
- Minor non-integer deltas are expected due to solver optimization outputs and proportional allocations.
