# Neighbor Approval Policy Report

Generated: 2026-03-11

## Scope
This report verifies the escalation-layer policy split:
- Scenario runs: neighbor aid auto-accepted (`scenario_auto_chain`)
- Operational runs (`live`/`production`/`manual`): neighbor aid created as pending and requires explicit approval (`governed_chain`)

Solver model behavior and optimization outputs were not modified by this policy change.

## Implementation Summary
Files updated:
- `backend/app/services/request_service.py`
- `backend/app/services/mutual_aid_service.py`
- `backend/app/routers/state.py`
- `backend/app/models/mutual_aid_offer.py`
- `backend/app/database.py`
- `backend/app/services/scenario_service.py`

Policy logic:
- Run mode normalization enforces allowed values: `scenario`, `live`, `production`, `manual` (`normal` maps to `manual`).
- Scenario mode auto-accepts seeded neighbor offers with provenance:
  - `auto_accepted = 1`
  - `approval_source = "scenario_auto"`
  - escalation mode `scenario_auto_chain`
- Non-scenario mode seeds pending offers only:
  - `status = "pending"`
  - `auto_accepted = 0`
  - `approval_source = "state_authority"`
  - escalation mode `governed_chain`
- State market offer creation endpoint no longer auto-accepts on behalf of requester.

## Scenario Auto Approval Verification
Validation run:
- Command: `python backend/run_scenario_system_certification.py --stress-runs 20 --json-out SCENARIO_SYSTEM_CERTIFICATION_POLICY_20.json --md-out SCENARIO_SYSTEM_CERTIFICATION_POLICY_20.md`

Observed (`SCENARIO_SYSTEM_CERTIFICATION_POLICY_20.json`):
- `neighbor_escalation.final_escalation_status.neighbor_offers_created = 0`
- `neighbor_escalation.final_escalation_status.neighbor_offers_accepted = 1`
- `neighbor_escalation.final_escalation_status.mode = "scenario_auto_chain"`
- `certification.status = "CERTIFIED"`

Stress (20 scenarios):
- Neighbor activation observed in stress distribution (`neighbor_state` non-zero)
- Severe neighbor non-zero rate: `0.470588`
- No demand realism violations: `0`

## Operational Approval Enforcement Verification
Targeted operational check executed with a synthetic `live` solver run and escalation trigger.

Observed:
- `offers_created = 3`
- `offers_pending = 3`
- `offers_accepted = 0`
- audit mode payload: `governed_chain`

Additional provenance sample:
- Recent auto-accepted offers show `approval_source = "scenario_auto"`
- Pending governed offers retain `approval_source = "state_authority"`

## Escalation Integrity Confirmation
Confirmed behaviors:
- Scenario simulation chain proceeds autonomously and preserves neighbor activation.
- Operational chain creates neighbor requests and waits for explicit acceptance.
- Governance provenance is persisted on offers (`auto_accepted`, `approval_source`).
- Solver path remains unchanged; policy is enforced in escalation/approval handling only.

## Final Status
Policy objective achieved:
- Scenario: auto-accepted neighbor aid
- Operational: approval-gated neighbor aid
- End-to-end certification remained passing for scenario workload
