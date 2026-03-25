# Scenario System Certification Report

Generated: 2026-03-11T15:36:17.846858+00:00
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
- Stress fairness avg: `0.914283`
- Stress fairness min: `0.557107`
- Stress service ratio avg: `0.925008`

## Escalation Usage
- Distribution pct: `{'district': 0.510512, 'state': 0.128569, 'neighbor_state': 0.233222, 'national': 0.127697}`
- Severe neighbor non-zero rate: `0.527778`

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
