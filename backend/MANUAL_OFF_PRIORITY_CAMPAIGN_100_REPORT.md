# Manual-Off Priority Campaign (100 Runs)

- Started: 2026-02-23T17:22:12Z
- Ended: 2026-02-23T17:25:07Z
- API Base: http://127.0.0.1:8000
- Mode Policy: PRIORITY_URGENCY_INFLUENCE_MODE=off (manual-first decision path)

## Overall Summary
- Total Runs: 100
- Solver Completed: 100
- Requests Accepted: 100
- Manual Rank Effective Source Count: 0
- Predicted Rank Effective Source Count: 0
- Default Rank Effective Source Count: 0
- State Escalation Seen: 0
- National Escalation Seen: 0
- Neighbor Offers Attempted/OK: 0/0
- State Aid Attempted/OK: 0/0
- National Aid Attempted/OK: 0/0
- Claim Actions Attempted/OK: 0/0
- Demand-Allocation Lineage Balanced Runs: 100
- Avg Allocation Ratio: 0.977778
- Avg Unmet Ratio: 0.022222

## First 50 Runs Focus
- Runs: 50
- Solver Completed: 50
- State Escalations Seen: 0
- National Escalations Seen: 0
- Avg Allocation Ratio: 0.977778
- Avg Unmet Ratio: 0.022222

## Variant Coverage
- deferred_t3_medium: runs=10 completed=10 state_escalations=0 national_escalations=0
- emergency_t0_critical: runs=10 completed=10 state_escalations=0 national_escalations=0
- future_rebound: runs=10 completed=10 state_escalations=0 national_escalations=0
- future_t4_high_claim: runs=10 completed=10 state_escalations=0 national_escalations=0
- low_stock_push: runs=10 completed=10 state_escalations=0 national_escalations=0
- low_t1_noncritical: runs=10 completed=10 state_escalations=0 national_escalations=0
- mid_t2_balanced: runs=10 completed=10 state_escalations=0 national_escalations=0
- national_pressure: runs=10 completed=10 state_escalations=0 national_escalations=0
- rankless_ml_candidate: runs=10 completed=10 state_escalations=0 national_escalations=0
- state_pressure: runs=10 completed=10 state_escalations=0 national_escalations=0

## Notes on Optimality Under Constraints
- Optimality is evaluated as solver-feasibility consistency: final_demand ~= allocated + unmet for each completed run.
- High unmet in low-stock and emergency variants is expected behavior under finite district/state/national stock constraints.
- State and national pool aid attempts validate that escalated demand can be serviced by higher-level pools when available.

## Raw Detail
- Full per-run detail is in DISTRICT603_LIVE_CAMPAIGN_REPORT.json under key `manual_off_priority_campaign_100`.
