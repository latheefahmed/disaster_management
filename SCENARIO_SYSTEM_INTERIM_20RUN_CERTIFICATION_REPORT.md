# Scenario System Certification Report

Generated: 2026-03-10T16:59:26.467630+00:00
Overall Certification: **NOT_CERTIFIED**

## Solver Behavior Summary
- Forced neighbor test status: `not_activated`
- Forced run scopes (final): `{'district': 261.0, 'state': 0.0, 'neighbor_state': 0.0, 'national': 0.0}`
- Escalation order preserved: `True`

## Invariants
- Stock conservation (district proxy): `True`
- Negative inventory rows: `0`
- Over-allocation slots: `0`

## Fairness and Service
- Stress fairness avg: `0.928434`
- Stress fairness min: `0.634269`
- Stress service ratio avg: `0.908780`

## Escalation Usage
- Distribution pct: `{'district': 0.005669, 'state': 0.213068, 'neighbor_state': 0.0, 'national': 0.781263}`
- Severe neighbor non-zero rate: `0.000000`

## Demand Realism
- Violations outside [0.5x, 3x]: `0`

## Priority and Timestep
- Priority pass: `True`
- Timestep pass: `True`

## Neighbor Diagnostics
- Candidate neighbors: `[{'state_code': '10', 'distance_km': None}, {'state_code': '11', 'distance_km': None}, {'state_code': '12', 'distance_km': None}, {'state_code': '13', 'distance_km': None}, {'state_code': '14', 'distance_km': None}, {'state_code': '15', 'distance_km': None}]`
- Cost hierarchy evidence: `{'solver_level_flow_cost': {'district': 1.0, 'state': 2.0, 'neighbor_state': 2.5, 'national': 3.0}, 'note': 'Neighbor is represented through confirmed inter-state aid provenance on state allocations; national remains highest cost level.'}`

## Certification Criteria
- stock conservation holds: `True`
- fairness >= 0.85: `True`
- priority affects allocation: `True`
- timestep affects allocation: `True`
- neighbor escalation activates: `False`
- escalation order preserved: `True`
- scenario demand bounded: `True`
