# Scenario System Certification Report

Generated: 2026-03-11T16:16:16.279481+00:00
Overall Certification: **CERTIFIED**

## Solver Behavior Summary
- Forced neighbor test status: `activated`
- Forced run scopes (final): `{'district': 6.0, 'state': 25.0, 'neighbor_state': 44.0, 'national': 10.0}`
- Escalation order preserved: `True`

## Invariants
- Stock conservation (district proxy): `True`
- Negative inventory rows: `0`
- Over-allocation slots: `0`

## Fairness and Service
- Stress fairness avg: `0.912745`
- Stress fairness min: `0.542566`
- Stress service ratio avg: `0.970190`

## Escalation Usage
- Distribution pct: `{'district': 0.638367, 'state': 0.059134, 'neighbor_state': 0.235866, 'national': 0.066633}`
- Severe neighbor non-zero rate: `0.470588`

## Demand Realism
- Violations outside [0.5x, 3x]: `0`

## Priority and Timestep
- Priority pass: `True`
- Timestep pass: `True`

## Neighbor Diagnostics
- Candidate neighbors: `[{'state_code': '10', 'distance_km': None}, {'state_code': '11', 'distance_km': None}, {'state_code': '12', 'distance_km': None}, {'state_code': '13', 'distance_km': None}, {'state_code': '14', 'distance_km': None}, {'state_code': '15', 'distance_km': None}]`
- Cost hierarchy evidence: `{'solver_level_flow_cost': {'district': 1.0, 'state': 2.0, 'neighbor_state': 2.3, 'national': 3.0}, 'note': 'Neighbor is represented through confirmed inter-state aid provenance on state allocations; national remains highest cost level.'}`

## Certification Criteria
- stock conservation holds: `True`
- fairness >= 0.85: `True`
- priority affects allocation: `True`
- timestep affects allocation: `True`
- neighbor escalation activates: `True`
- escalation order preserved: `True`
- scenario demand bounded: `True`
