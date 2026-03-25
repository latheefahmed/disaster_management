# Scenario System Certification Report

Generated: 2026-03-10T15:41:10.653101+00:00
Overall Certification: **NOT_CERTIFIED**

## Solver Behavior Summary
- Forced neighbor test status: `not_activated`
- Forced run scopes (final): `{'district': 0.0, 'state': 1.0, 'neighbor_state': 0.0, 'national': 0.0}`
- Escalation order preserved: `True`

## Invariants
- Stock conservation (district proxy): `True`
- Negative inventory rows: `0`
- Over-allocation slots: `0`

## Fairness and Service
- Stress fairness avg: `0.893750`
- Stress fairness min: `0.500511`
- Stress service ratio avg: `0.850901`

## Escalation Usage
- Distribution pct: `{'district': 0.008291, 'state': 0.200076, 'neighbor_state': 1e-05, 'national': 0.791624}`
- Severe neighbor non-zero rate: `0.014706`

## Demand Realism
- Violations outside [0.5x, 3x]: `0`

## Priority and Timestep
- Priority pass: `False`
- Timestep pass: `True`

## Neighbor Diagnostics
- Candidate neighbors: `[{'state_code': '10', 'distance_km': None}, {'state_code': '11', 'distance_km': None}, {'state_code': '12', 'distance_km': None}, {'state_code': '13', 'distance_km': None}, {'state_code': '14', 'distance_km': None}, {'state_code': '15', 'distance_km': None}]`
- Cost hierarchy evidence: `{'solver_level_flow_cost': {'district': 1.0, 'state': 2.0, 'neighbor_state': 2.5, 'national': 3.0}, 'note': 'Neighbor is represented through confirmed inter-state aid provenance on state allocations; national remains highest cost level.'}`

## Certification Criteria
- stock conservation holds: `True`
- fairness >= 0.85: `True`
- priority affects allocation: `False`
- timestep affects allocation: `True`
- neighbor escalation activates: `False`
- escalation order preserved: `True`
- scenario demand bounded: `True`
