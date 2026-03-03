# Performance & Evaluation Metrics Report
**System Performance, Validation Matrices, and Execution Data**

## 1. Executive Summary
This document consolidates all the empirical data, stability matrices, performance probes, and integration test reports associated with the disaster management system operations. Extensive load operations verified latency boundaries, optimization constraints, and API operational resilience.

## 2. Quantitative Summaries

### ADMIN_60_STRESS_CERT_REPORT.json
```json
{
  "generated_at": "2026-03-01T09:32:40.572411+00:00",
  "runs_requested": 20,
  "runs_executed": 20,
  "run_scope": "focused",
  "pass_count": 20,
  "fail_count": 0,
  "overall_status": "PASS",
  "cycles": [
    {
      "cycle": 1,
      "preset": "very_low",
      "started_at": "2026-03-01T09:03:11.702764+00:00",
      "run_scope": "focused",
      "scenario_name": "AUTO_ADMIN_60_STRESS_1_090311",
      "scenario_id": 231,
      "create_status": 200,
      "preview_status": 200,
      "apply_status": 200,
      "run_status": 200,
      "run_detail": null,
      "run_id": 931,
      "summary_status": 200,
      "followup_run_status": null,
      "followup_run_id": null,
      "followup_summary_status": null,
      "revert_status": 200,
      "verify_status": 200,
      "followup_revert_status": null,
      "followup_verify_status": null,
      "verify_ok": true,
      "verify_net_total": 0.0,
      "verify_debit_total": -1331.0,
      "verify_revert_total": 1331.0,
      "followup_verify_ok": null,
      "followup_verify_net_total": null,
      "manual_aid": {
        "aid_requests_created": 0,
        "offers_created": 0,
        "offers_accepted": 0,
        "accepted_quantity": 0.0
      },
      "fairness": {
        "district_ratio_jain": 1.0,
        "state_ratio_jain": 1.0,
        "district_ratio_gap": 0.0,
        "state_ratio_gap": 0.0,
        "time_service_early_avg": 1.0,
        "time_service_late_avg": 1.0,
        "district_entities": 14,
        "state_enti
```
*(Output truncated for brevity)*

### ADMIN_DASHBOARD_SMOKE_REPORT.json
```json
{
  "generated_at": "2026-03-01T17:24:59.039069+00:00",
  "scenario_id": 256,
  "run_id": 963,
  "overall_status": "PASS",
  "summary": {
    "passed": 18,
    "failed": 0,
    "checks_total": 18,
    "preset_checks": 5
  },
  "checks": [
    {
      "check": "login_admin",
      "ok": true,
      "status": 200
    },
    {
      "check": "list_scenarios",
      "ok": true,
      "status": 200
    },
    {
      "check": "create_scenario",
      "ok": true,
      "status": 200,
      "scenario_id": 256
    },
    {
      "check": "preview_very_low",
      "ok": true,
      "status": 200,
      "row_count": 264,
      "ratio": 0.6101
    },
    {
      "check": "preview_low",
      "ok": true,
      "status": 200,
      "row_count": 420,
      "ratio": 0.9017
    },
    {
      "check": "preview_medium",
      "ok": true,
      "status": 200,
      "row_count": 312,
      "ratio": 1.1713
    },
    {
      "check": "preview_high",
      "ok": true,
      "status": 200,
      "row_count": 504,
      "ratio": 1.5888
    },
    {
      "check": "preview_extreme",
      "ok": true,
      "status": 200,
      "row_count": 750,
      "ratio": 2.3434
    },
    {
      "check": "apply_randomizer",
      "ok": true,
      "status": 200,
      "applied_rows": 1000
    },
    {
      "check": "run_scenario",
      "ok": true,
      "status": 200
    },
    {
      "check": "list_runs_and_pick_run_id",
      "ok": true,
      "status": 200,
      "run_id": 963
    },
    {
      "check":
```
*(Output truncated for brevity)*

### ADMIN_SCENARIO_CERT_CHECKPOINT.json
```json
{
  "generated_at": "2026-02-28T20:43:15.357364+00:00",
  "target_runs": 30,
  "executed_runs": 30,
  "pass_count": 15,
  "fail_count": 15,
  "overall_status": "FAIL",
  "scenarios_created": [
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    43
  ],
  "cycles": [
    {
      "cycle": 1,
      "preset": "very_low",
      "scenario_name": "AUTO_ADMIN_CERT_1_180815",
      "scenario_id": 14,
      "create_status": 200,
      "randomizer_preview_status": 200,
      "randomizer_apply_status": 200,
      "run_status": 200,
      "run_id": 722,
      "summary_status": 200,
      "revert_status": 200,
      "verify_status": 200,
      "verify_ok": true,
      "verify_net_total": 0.0,
      "verify_debit_total": -16848.0,
      "verify_revert_total": 16848.0,
      "pass": true,
      "notes": [],
      "started_at": "2026-02-28T18:08:15.224115+00:00",
      "finished_at": "2026-02-28T18:11:17.656458+00:00",
      "runs_list_status": 200
    },
    {
      "cycle": 2,
      "preset": "low",
      "scenario_name": "AUTO_ADMIN_CERT_2_181117",
      "scenario_id": 15,
      "create_status": 200,
      "randomizer_preview_status": 200,
      "randomizer_apply_status": 200,
      "run_status": 500,
      "run_id": 723,
      "summary_status": 200,
      "revert_status": 200,
      "verify_status": 200,
   
```
*(Output truncated for brevity)*

### ADMIN_SCENARIO_CERT_ENRICHED_RUN_OBJECTS.json
```json
{
  "generated_at": "2026-03-01T04:59:48.535525+00:00",
  "source_report": "C:\\Users\\LATHEEF\\Desktop\\disaster_management\\backend\\ADMIN_SCENARIO_CERT_REPORT.json",
  "target_runs": 30,
  "executed_runs": 30,
  "pass_count": 30,
  "fail_count": 0,
  "overall_status": "PASS",
  "run_objects": [
    {
      "cycle": 1,
      "preset": "very_low",
      "scenario_id": 79,
      "scenario_name": "AUTO_ADMIN_CERT_1_045349",
      "run_id": 777,
      "cert_status": {
        "pass": true,
        "notes": [],
        "run_status": 200,
        "summary_status": 200,
        "revert_status": 200,
        "verify_status": 200,
        "verify_ok": true,
        "verify_net_total": 0.0,
        "verify_debit_total": -60.0,
        "verify_revert_total": 60.0
      },
      "scenario_run_db_status": "completed",
      "summary_endpoint_status": 200,
      "summary": {
        "run_id": 777,
        "scenario_id": 79,
        "status": "completed",
        "started_at": "2026-03-01T04:53:51.242498",
        "totals": {
          "allocated_quantity": 60.0,
          "unmet_quantity": 0.0,
          "districts_covered": 3,
          "districts_met": 3,
          "districts_unmet": 0,
          "allocation_rows": 12,
          "unmet_rows": 0
        },
        "district_breakdown": [
          {
            "district_code": "13",
            "allocated_quantity": 20.0,
            "unmet_quantity": 0.0,
            "met": true
          },
          {
            "district_code": "2
```
*(Output truncated for brevity)*

### ADMIN_SCENARIO_CERT_REPORT.json
```json
{
  "generated_at": "2026-03-01T04:57:15.632028+00:00",
  "run_scope": "focused",
  "target_runs": 30,
  "executed_runs": 30,
  "pass_count": 30,
  "fail_count": 0,
  "overall_status": "PASS",
  "scenarios_created": [
    79,
    80,
    81,
    82,
    83,
    84,
    85,
    86,
    87,
    88,
    89,
    90,
    91,
    92,
    93,
    94,
    95,
    96,
    97,
    98,
    99,
    100,
    101,
    102,
    103,
    104,
    105,
    106,
    107,
    108
  ],
  "cycles": [
    {
      "cycle": 1,
      "preset": "very_low",
      "scenario_name": "AUTO_ADMIN_CERT_1_045349",
      "scenario_id": 79,
      "create_status": 200,
      "randomizer_preview_status": 200,
      "randomizer_apply_status": 200,
      "run_status": 200,
      "run_failure_detail": null,
      "run_failure_class": null,
      "run_retry_count": 0,
      "run_id": 777,
      "summary_status": 200,
      "revert_status": 200,
      "verify_status": 200,
      "verify_ok": true,
      "verify_net_total": 0.0,
      "verify_debit_total": -60.0,
      "verify_revert_total": 60.0,
      "randomizer_demand_ratio": 0.5979,
      "randomizer_row_count": 18,
      "randomizer_warning_count": 0,
      "variant_used": {
        "preset": "very_low",
        "seed": 20260318,
        "time_horizon": 2,
        "district_count": 3,
        "resource_count": 3,
        "stress_mode": false,
        "replace_existing": true,
        "state_codes": [
          "1",
          "2"
        ]
      },
      "pass": t
```
*(Output truncated for brevity)*

### BACKEND_AUTONOMOUS_GATEWAY_SUMMARY.json
```json
{
  "generated_at": "2026-03-02T15:44:47.639628+00:00",
  "startup_metrics": {
    "import_time_ms": 10016.337700013537,
    "migration_time_ms": 15025.061699998332,
    "seed_time_ms": 15022.942999989027,
    "import_status": "timeout",
    "migration_status": "timeout",
    "seed_status": "timeout"
  },
  "stale_running_after_start": 0,
  "log_file": "C:\\Users\\LATHEEF\\Desktop\\disaster_management\\backend\\BACKEND_AUTONOMOUS_GATEWAY_LOG.jsonl"
}
```
### baseline_snapshot.json
```json
{
  "district_stock": [
    {
      "resource_id": "R1",
      "district_stock": 0.0,
      "state_stock": 608307094.0,
      "national_stock": 2656370252.0,
      "in_transit": 20.0,
      "available_stock": 3264677326.0
    },
    {
      "resource_id": "R2",
      "district_stock": 148072548955.13367,
      "state_stock": 177907304.0,
      "national_stock": 6729.0,
      "in_transit": 0.0,
      "available_stock": 148250462988.13367
    },
    {
      "resource_id": "R3",
      "district_stock": 0.0,
      "state_stock": 152493252.0,
      "national_stock": 1538919875.0,
      "in_transit": 20.0,
      "available_stock": 1691413107.0
    },
    {
      "resource_id": "R4",
      "district_stock": 8885167984.40569,
      "state_stock": 40664516.0,
      "national_stock": 207710574.0,
      "in_transit": 0.0,
      "available_stock": 9133543074.40569
    },
    {
      "resource_id": "R5",
      "district_stock": 0.0,
      "state_stock": 1220006089.9375484,
      "national_stock": 2336.0,
      "in_transit": 20.0,
      "available_stock": 1220008405.9375484
    },
    {
      "resource_id": "R6",
      "district_stock": 191990616604.807,
      "state_stock": 7624597009.0,
      "national_stock": 38945465970.0,
      "in_transit": 0.0,
      "available_stock": 238560679583.807
    },
    {
      "resource_id": "R7",
      "district_stock": 150908232433.60526,
      "state_stock": 1016612918.0,
      "national_stock": 5257700929.0,
      "in_transit": 0.0,
      "available_s
```
*(Output truncated for brevity)*

### debug_suite_results.json
```json
{
  "generated_at": "2026-02-20T17:15:01.896515+00:00",
  "tests": {
    "district_test": {
      "run_id": 194,
      "run_status": "running",
      "metrics": {
        "final": 0.0,
        "alloc": 0.0,
        "unmet": 0.0,
        "conservation_ok": true
      },
      "expected": {
        "final": 10.0,
        "alloc": 10.0,
        "unmet": 0.0
      },
      "pass": false
    },
    "state_cover_test": {
      "scenario_id": 50,
      "run_id": 195,
      "run_status": "completed",
      "metrics": {
        "final": 10.0,
        "alloc": 10.0,
        "unmet": 0.0,
        "conservation_ok": true
      },
      "expected": {
        "alloc": 10.0,
        "unmet": 0.0
      },
      "pass": true
    },
    "national_cover_test": {
      "scenario_id": 51,
      "run_id": 196,
      "run_status": "completed",
      "metrics": {
        "final": 10.0,
        "alloc": 10.0,
        "unmet": 0.0,
        "conservation_ok": true
      },
      "expected": {
        "alloc": 10.0,
        "unmet": 0.0
      },
      "pass": true
    },
    "full_shortage_test": {
      "scenario_id": 52,
      "run_id": 197,
      "run_status": "completed",
      "metrics": {
        "final": 100.0,
        "alloc": 3.0,
        "unmet": 97.0,
        "conservation_ok": true
      },
      "expected": {
        "alloc": 3.0,
        "unmet": 97.0
      },
      "pass": true
    },
    "escalation_test": {
      "request_id": 164,
      "status_before": "pending",
      "status_after_e
```
### DISTRICT603_LIVE_CAMPAIGN_REPORT.json
```json
{
  "started_at": "2026-02-22T16:05:42Z",
  "base_url": "http://127.0.0.1:8000",
  "cases": [
    {
      "case_id": 1,
      "resource_id": "R1",
      "resource_name": "food_packets",
      "class": "consumable",
      "solver_run_id": 2,
      "time": 0,
      "allocated_qty": 1.0,
      "attempt_qty": 1,
      "claim_status": 200,
      "consume_status": 200,
      "return_status": "N/A",
      "pre_district": 852693395.8794732,
      "pre_state": 508306459.0,
      "pre_national": 2596364290.0,
      "pre_available": 3957364144.879473,
      "claim_detail": null,
      "consume_detail": null,
      "post_district": 852693395.8794732,
      "post_state": 508306459.0,
      "post_national": 2596364290.0,
      "post_available": 3957364144.879473,
      "delta_district": 0.0,
      "delta_state": 0.0,
      "delta_national": 0.0,
      "delta_available": 0.0
    },
    {
      "case_id": 2,
      "resource_id": "R10",
      "resource_name": "blankets",
      "class": "non_consumable",
      "solver_run_id": 2,
      "time": 0,
      "allocated_qty": 1.0,
      "attempt_qty": 1,
      "claim_status": 200,
      "consume_status": "N/A",
      "return_status": 200,
      "pre_district": 326865488.46742046,
      "pre_state": 194850808.0,
      "pre_national": 995272975.0,
      "pre_available": 1516989271.4674206,
      "claim_detail": null,
      "return_detail": null,
      "post_district": 326865489.46742046,
      "post_state": 194850808.0,
      "post_national": 995272975
```
*(Output truncated for brevity)*

### expanded_matrix_verification.json
```json
{
  "generated_at": "2026-02-21T07:53:59.243492+00:00",
  "coverage": {
    "district_count": 7,
    "state_count": 2,
    "resource_count": 14,
    "synthetic_run_id": 17,
    "scenario_rows_inserted": 98,
    "synthetic_allocations_for_run": 100,
    "total_pool_transactions_after_checks": 37
  },
  "selected": {
    "states": [
      "1",
      "10",
      "11"
    ],
    "districts": [
      "1",
      "10",
      "11",
      "12",
      "1001",
      "1002",
      "1003"
    ],
    "returnable_resource": "R10",
    "consumable_resource": "R1"
  },
  "checks": {
    "district_endpoint_pass": 35,
    "district_endpoint_total": 35,
    "district_action_pass": 7,
    "district_action_total": 7,
    "state_action_pass": 4,
    "state_action_total": 4,
    "national_action_pass": 3,
    "national_action_total": 3,
    "mutual_aid_pass": 2,
    "mutual_aid_total": 2,
    "frontend_wiring_pass": 4,
    "frontend_wiring_total": 4
  },
  "details": {
    "district_users": [
      "verify_d_1",
      "verify_d_10",
      "verify_d_11",
      "verify_d_12",
      "verify_d_1001",
      "verify_d_1002",
      "verify_d_1003"
    ],
    "state_users": [
      "verify_s_1",
      "verify_s_10",
      "verify_s_11"
    ],
    "district_checks": [
      {
        "user": "verify_d_1",
        "path": "/district/me",
        "status": 200,
        "ok": true,
        "body": {
          "district_code": "1",
          "district_name": "Kupwara",
          "state_code": "1",
          "dem
```
*(Output truncated for brevity)*

### LIVE_POOL_CERT_CHECKPOINT.json
```json
{
  "started_at": "2026-03-01T17:50:35Z",
  "config": {
    "district_code": "603",
    "parent_state": "33",
    "target_completed_runs": 15,
    "max_attempts": 30,
    "neighbor_state": "1"
  },
  "baseline_snapshot": {
    "district_stock": [
      {
        "resource_id": "R1",
        "district_stock": 0.0,
        "state_stock": 608307094.0,
        "national_stock": 2656370252.0,
        "in_transit": 20.0,
        "available_stock": 3264677326.0
      },
      {
        "resource_id": "R2",
        "district_stock": 148072548955.13367,
        "state_stock": 177907304.0,
        "national_stock": 6729.0,
        "in_transit": 0.0,
        "available_stock": 148250462988.13367
      },
      {
        "resource_id": "R3",
        "district_stock": 0.0,
        "state_stock": 152493252.0,
        "national_stock": 1538919875.0,
        "in_transit": 20.0,
        "available_stock": 1691413107.0
      },
      {
        "resource_id": "R4",
        "district_stock": 8885167984.40569,
        "state_stock": 40664516.0,
        "national_stock": 207710574.0,
        "in_transit": 0.0,
        "available_stock": 9133543074.40569
      },
      {
        "resource_id": "R5",
        "district_stock": 0.0,
        "state_stock": 1220006089.9375484,
        "national_stock": 2336.0,
        "in_transit": 20.0,
        "available_stock": 1220008405.9375484
      },
      {
        "resource_id": "R6",
        "district_stock": 191990616604.807,
        "state_stock": 762459700
```
*(Output truncated for brevity)*

### LIVE_POOL_CERT_REPORT.json
```json
{
  "started_at": "2026-02-28T06:30:51Z",
  "config": {
    "district_code": "603",
    "parent_state": "33",
    "target_completed_runs": 60,
    "max_attempts": 120,
    "neighbor_state": "1"
  },
  "baseline_snapshot": {
    "district_stock": [
      {
        "resource_id": "R1",
        "district_stock": 0.0,
        "state_stock": 608307094.0,
        "national_stock": 2656370252.0,
        "in_transit": 20.0,
        "available_stock": 3264677326.0
      },
      {
        "resource_id": "R2",
        "district_stock": 148072548955.13367,
        "state_stock": 177907304.0,
        "national_stock": 6729.0,
        "in_transit": 0.0,
        "available_stock": 148250462988.13367
      },
      {
        "resource_id": "R3",
        "district_stock": 0.0,
        "state_stock": 152493252.0,
        "national_stock": 1538919875.0,
        "in_transit": 20.0,
        "available_stock": 1691413107.0
      },
      {
        "resource_id": "R4",
        "district_stock": 8885167984.40569,
        "state_stock": 40664516.0,
        "national_stock": 207710574.0,
        "in_transit": 0.0,
        "available_stock": 9133543074.40569
      },
      {
        "resource_id": "R5",
        "district_stock": 0.0,
        "state_stock": 1220006089.9375484,
        "national_stock": 2336.0,
        "in_transit": 20.0,
        "available_stock": 1220008405.9375484
      },
      {
        "resource_id": "R6",
        "district_stock": 191990616604.807,
        "state_stock": 76245970
```
*(Output truncated for brevity)*

### manual_solver_validation_report.json
```json
[
  {
    "label": "LIVE_DEMAND",
    "passed": true,
    "return_code": 0,
    "status": "Optimal",
    "allocation_rows": 37276,
    "unmet_rows": 22589,
    "total_allocated": 130466676.05721554,
    "total_unmet": 4631471389.826885,
    "run_summary_status": "Optimal",
    "run_summary_objective": 4631471555273497.0
  },
  {
    "label": "SCENARIO_4",
    "passed": true,
    "return_code": 0,
    "status": "Optimal",
    "allocation_rows": 58559,
    "unmet_rows": 143,
    "total_allocated": 2064961030032.732,
    "total_unmet": 344100905814.62427,
    "run_summary_status": "Optimal",
    "run_summary_objective": 3.4410502915206464e+17
  }
]
```
### manual_validation_suite_report.json
```json
{
  "generated_at": "2026-02-16T16:08:23.889943Z",
  "totals": {
    "total_cases": 53,
    "green": 52,
    "yellow": 0,
    "red": 1,
    "pass_rate": 0.9811
  },
  "confidence": "high",
  "cases": [
    {
      "name": "Operational-01: district me",
      "ok": true,
      "color": "green",
      "detail": "status=200"
    },
    {
      "name": "Operational-02: district demand-mode get",
      "ok": true,
      "color": "green",
      "detail": "status=200"
    },
    {
      "name": "Operational-03: district demand-mode put human_only",
      "ok": true,
      "color": "green",
      "detail": "status=200"
    },
    {
      "name": "Operational-04: district demand-mode put ai_human",
      "ok": true,
      "color": "green",
      "detail": "status=200"
    },
    {
      "name": "Operational-05: district allocations",
      "ok": true,
      "color": "green",
      "detail": "status=200"
    },
    {
      "name": "Operational-06: district unmet",
      "ok": true,
      "color": "green",
      "detail": "status=200"
    },
    {
      "name": "Operational-07: district solver-status",
      "ok": true,
      "color": "green",
      "detail": "status=200"
    },
    {
      "name": "Operational-08: district request unknown rejected",
      "ok": true,
      "color": "green",
      "detail": "status=400"
    },
    {
      "name": "Operational-09: district request-batch unknown rejected",
      "ok": true,
      "color": "green",
      "detail": "status=400"
    },
    {
```
*(Output truncated for brevity)*

### OVERFLOW_RECONCILIATION_APPLY_finish_1.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 2000,
  "returned": 427,
  "refilled": 1371,
  "skipped": 12202,
  "failed": 0,
  "returned_quantity": 1708.0,
  "refilled_quantity": 311416431.0,
  "errors": [],
  "max_process": 2000,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T105947Z",
  "applied": true,
  "generated_at": "2026-02-28T11:10:58.147498Z"
}
```
### OVERFLOW_RECONCILIATION_APPLY_finish_2.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 2000,
  "returned": 515,
  "refilled": 1263,
  "skipped": 14330,
  "failed": 0,
  "returned_quantity": 2060.0,
  "refilled_quantity": 201225807.0,
  "errors": [],
  "max_process": 2000,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T111155Z",
  "applied": true,
  "generated_at": "2026-02-28T11:22:16.956373Z"
}
```
### OVERFLOW_RECONCILIATION_APPLY_round_1.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 1500,
  "returned": 467,
  "refilled": 1033,
  "skipped": 222,
  "failed": 11,
  "returned_quantity": 1868.0,
  "refilled_quantity": 281984232.0,
  "errors": [
    {
      "allocation_id": 32935,
      "solver_run_id": 701,
      "district_code": "603",
      "resource_id": "R13",
      "time": 0,
      "error": "Cannot claim in allocation status 'RETURNED'"
    },
    {
      "allocation_id": 32791,
      "solver_run_id": 699,
      "district_code": "603",
      "resource_id": "R10",
      "time": 4,
      "error": "quantity exceeds max allowed for resource 'R10' (5000000)"
    },
    {
      "allocation_id": 32505,
      "solver_run_id": 692,
      "district_code": "603",
      "resource_id": "R12",
      "time": 1,
      "error": "Cannot claim in allocation status 'RETURNED'"
    },
    {
      "allocation_id": 32400,
      "solver_run_id": 690,
      "district_code": "603",
      "resource_id": "R12",
      "time": 1,
      "error": "Cannot claim in allocation status 'RETURNED'"
    },
    {
      "allocation_id": 32307,
      "solver_run_id": 688,
      "district_code": "603",
      "resource_id": "R56",
      "time": 4,
      "error": "Cannot claim in allocation status 'RETURNED'"
    },
    {
      "allocation_id": 32096,
      "solver_run_id": 684,
      "district_code": "603",
      "resource_id": "R54",
      "time": 0,
      "error": "
```
*(Output truncated for brevity)*

### OVERFLOW_RECONCILIATION_APPLY_round_complete_1.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 2000,
  "returned": 733,
  "refilled": 1263,
  "skipped": 22406,
  "failed": 0,
  "returned_quantity": 13997973.0,
  "refilled_quantity": 171515542.0,
  "errors": [],
  "max_process": 2000,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T125648Z",
  "applied": true,
  "generated_at": "2026-02-28T13:04:20.822477Z",
  "validation": {
    "keep_latest": 300,
    "scope": "all",
    "overflow_candidates": 31493,
    "unresolved_overflow": 6999,
    "invalid_mode_for_returnable": 0,
    "invalid_mode_for_non_returnable": 0,
    "mode_counts": {
      "refilled_non_returnable": 16100,
      "returned": 8151,
      "skipped_returned_status": 124,
      "skipped_zero_remaining": 26,
      "": 7092
    },
    "ok": false,
    "issues": [
      "unresolved_overflow=6999"
    ]
  }
}
```
### OVERFLOW_RECONCILIATION_APPLY_round_complete_2.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 2000,
  "returned": 744,
  "refilled": 1253,
  "skipped": 24405,
  "failed": 0,
  "returned_quantity": 6005840.0,
  "refilled_quantity": 9235.0,
  "errors": [],
  "max_process": 2000,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T130456Z",
  "applied": true,
  "generated_at": "2026-02-28T13:17:42.906103Z",
  "validation": {
    "keep_latest": 300,
    "scope": "all",
    "overflow_candidates": 31493,
    "unresolved_overflow": 4999,
    "invalid_mode_for_returnable": 0,
    "invalid_mode_for_non_returnable": 0,
    "mode_counts": {
      "refilled_non_returnable": 17353,
      "returned": 8894,
      "skipped_returned_status": 127,
      "skipped_zero_remaining": 27,
      "": 5092
    },
    "ok": false,
    "issues": [
      "unresolved_overflow=4999"
    ]
  }
}
```
### OVERFLOW_RECONCILIATION_APPLY_round_complete_A.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 2000,
  "returned": 740,
  "refilled": 1256,
  "skipped": 27476,
  "failed": 0,
  "returned_quantity": 11276582.0,
  "refilled_quantity": 10280163.0,
  "errors": [],
  "max_process": 2000,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T132826Z",
  "applied": true,
  "generated_at": "2026-02-28T13:42:46.180698Z",
  "validation": {
    "keep_latest": 300,
    "scope": "all",
    "overflow_candidates": 31493,
    "unresolved_overflow": 1966,
    "invalid_mode_for_returnable": 0,
    "invalid_mode_for_non_returnable": 0,
    "mode_counts": {
      "refilled_non_returnable": 19257,
      "returned": 10006,
      "skipped_returned_status": 131,
      "skipped_zero_remaining": 77,
      "": 2022
    },
    "ok": false,
    "issues": [
      "unresolved_overflow=1966"
    ]
  }
}
```
### OVERFLOW_RECONCILIATION_APPLY_round_complete_B.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 1938,
  "returned": 711,
  "refilled": 1217,
  "skipped": 29565,
  "failed": 0,
  "returned_quantity": 1195891.0,
  "refilled_quantity": 233775.0,
  "errors": [],
  "max_process": 2000,
  "run_id": "overflow-reconcile-20260228T134404Z",
  "applied": true,
  "generated_at": "2026-02-28T13:57:56.027255Z",
  "validation": {
    "keep_latest": 300,
    "scope": "all",
    "overflow_candidates": 31493,
    "unresolved_overflow": 0,
    "invalid_mode_for_returnable": 0,
    "invalid_mode_for_non_returnable": 0,
    "mode_counts": {
      "refilled_non_returnable": 20474,
      "returned": 10717,
      "skipped_returned_status": 141,
      "skipped_zero_remaining": 161
    },
    "ok": true,
    "issues": []
  }
}
```
### OVERFLOW_RECONCILIATION_APPLY_round_live_1.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 100,
  "returned": 18,
  "refilled": 70,
  "skipped": 10495,
  "failed": 1,
  "returned_quantity": 72.0,
  "refilled_quantity": 280.0,
  "errors": [
    {
      "allocation_id": 21641,
      "solver_run_id": 473,
      "district_code": "603",
      "resource_id": "R11",
      "time": 3,
      "error": "Claim quantity exceeds allocated quantity"
    }
  ],
  "max_process": 100,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T104438Z",
  "applied": true,
  "generated_at": "2026-02-28T10:45:44.629954Z"
}
```
### OVERFLOW_RECONCILIATION_APPLY_round_live_2.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 100,
  "returned": 23,
  "refilled": 69,
  "skipped": 10756,
  "failed": 0,
  "returned_quantity": 92.0,
  "refilled_quantity": 276.0,
  "errors": [],
  "max_process": 100,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T104720Z",
  "applied": true,
  "generated_at": "2026-02-28T10:48:30.240643Z"
}
```
### OVERFLOW_RECONCILIATION_APPLY_round_live_3.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 100,
  "returned": 19,
  "refilled": 70,
  "skipped": 10959,
  "failed": 0,
  "returned_quantity": 76.0,
  "refilled_quantity": 15000275.0,
  "errors": [],
  "max_process": 100,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T104921Z",
  "applied": true,
  "generated_at": "2026-02-28T10:50:28.138901Z"
}
```
### OVERFLOW_RECONCILIATION_APPLY_round_live_4.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 100,
  "returned": 22,
  "refilled": 69,
  "skipped": 11127,
  "failed": 0,
  "returned_quantity": 88.0,
  "refilled_quantity": 1581525.0,
  "errors": [],
  "max_process": 100,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T105119Z",
  "applied": true,
  "generated_at": "2026-02-28T10:52:22.312337Z"
}
```
### OVERFLOW_RECONCILIATION_APPLY_round_live_5.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": false,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 100,
  "returned": 21,
  "refilled": 68,
  "skipped": 11300,
  "failed": 0,
  "returned_quantity": 84.0,
  "refilled_quantity": 272.0,
  "errors": [],
  "max_process": 100,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T105312Z",
  "applied": true,
  "generated_at": "2026-02-28T10:54:13.457059Z"
}
```
### OVERFLOW_RECONCILIATION_DRYRUN.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": true,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 31388,
  "returned": 10914,
  "refilled": 20474,
  "skipped": 105,
  "failed": 0,
  "returned_quantity": 315058759.0,
  "refilled_quantity": 3426871552.0,
  "errors": [],
  "run_id": "overflow-reconcile-20260228T091206Z",
  "applied": false,
  "generated_at": "2026-02-28T09:12:08.612479Z"
}
```
### OVERFLOW_RECONCILIATION_DRYRUN_CHECK.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": true,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 2000,
  "returned": 662,
  "refilled": 1338,
  "skipped": 7934,
  "failed": 0,
  "returned_quantity": 196449851.0,
  "refilled_quantity": 358624949.0,
  "errors": [],
  "max_process": 2000,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T102707Z",
  "applied": false,
  "generated_at": "2026-02-28T10:27:09.693922Z"
}
```
### OVERFLOW_RECONCILIATION_DRYRUN_post_live5.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": true,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 2000,
  "returned": 630,
  "refilled": 1370,
  "skipped": 11415,
  "failed": 0,
  "returned_quantity": 16114964.0,
  "refilled_quantity": 346979564.0,
  "errors": [],
  "max_process": 2000,
  "stopped_early": true,
  "run_id": "overflow-reconcile-20260228T105515Z",
  "applied": false,
  "generated_at": "2026-02-28T10:55:17.205910Z"
}
```
### OVERFLOW_RECONCILIATION_POST_APPLY_DRYRUN.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": true,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 28549,
  "returned": 10032,
  "refilled": 18517,
  "skipped": 2944,
  "failed": 0,
  "returned_quantity": 315055231.0,
  "refilled_quantity": 3031795000.0,
  "errors": [],
  "max_process": null,
  "run_id": "overflow-reconcile-20260228T094415Z",
  "applied": false,
  "generated_at": "2026-02-28T09:44:16.537130Z"
}
```
### OVERFLOW_RECONCILIATION_STATUS_FINAL.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": true,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 0,
  "returned": 0,
  "refilled": 0,
  "skipped": 31493,
  "failed": 0,
  "returned_quantity": 0.0,
  "refilled_quantity": 0.0,
  "errors": [],
  "max_process": null,
  "run_id": "overflow-reconcile-20260228T135924Z",
  "applied": false,
  "generated_at": "2026-02-28T13:59:26.357271Z",
  "validation": {
    "keep_latest": 300,
    "scope": "all",
    "overflow_candidates": 31493,
    "unresolved_overflow": 0,
    "invalid_mode_for_returnable": 0,
    "invalid_mode_for_non_returnable": 0,
    "mode_counts": {
      "refilled_non_returnable": 20474,
      "returned": 10717,
      "skipped_returned_status": 141,
      "skipped_zero_remaining": 161
    },
    "ok": true,
    "issues": []
  }
}
```
### OVERFLOW_RECONCILIATION_STATUS_LATEST.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": true,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 14106,
  "returned": 5295,
  "refilled": 8811,
  "skipped": 17387,
  "failed": 0,
  "returned_quantity": 74918325.0,
  "refilled_quantity": 618308093.0,
  "errors": [],
  "max_process": null,
  "run_id": "overflow-reconcile-20260228T113020Z",
  "applied": false,
  "generated_at": "2026-02-28T11:30:22.829124Z"
}
```
### OVERFLOW_RECONCILIATION_STATUS_NOW.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "dry_run": true,
  "active_count": 300,
  "overflow_candidates": 31493,
  "processed": 19520,
  "returned": 7189,
  "refilled": 12331,
  "skipped": 11973,
  "failed": 0,
  "returned_quantity": 113970010.0,
  "refilled_quantity": 1518118152.0,
  "errors": [],
  "max_process": null,
  "run_id": "overflow-reconcile-20260228T105840Z",
  "applied": false,
  "generated_at": "2026-02-28T10:58:42.180897Z"
}
```
### OVERFLOW_RECONCILIATION_VALIDATION_FINAL.json
```json
{
  "keep_latest": 300,
  "scope": "all",
  "overflow_candidates": 31493,
  "unresolved_overflow": 0,
  "invalid_mode_for_returnable": 0,
  "invalid_mode_for_non_returnable": 0,
  "mode_counts": {
    "refilled_non_returnable": 20474,
    "returned": 10717,
    "skipped_returned_status": 141,
    "skipped_zero_remaining": 161
  },
  "ok": true,
  "issues": [],
  "generated_at": "2026-02-28T14:00:56.096064Z"
}
```
### PERFORMANCE_PROBE_INPROCESS_2026-03-01.json
*Could not parse JSON: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte*

### PERFORMANCE_PROBE_INPROCESS_RERUN_2026-03-01.json
*Could not parse JSON: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte*

### PERFORMANCE_PROBE_MATRIX_2026-03-01.json
*Could not parse JSON: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte*

### PERFORMANCE_PROBE_MATRIX_RERUN_2026-03-01.json
*Could not parse JSON: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte*

### PHASE10_LS_NMC_TEST_MATRIX.json
```json
{
  "version": "1.0.0",
  "invariants": [
    "Solver remains single source of truth",
    "Neural outputs are bounded knob proposals only",
    "No direct allocation, constraint mutation, or governance bypass",
    "Fallback controller is always available"
  ],
  "tests": [
    {
      "id": "D1",
      "scope": "district",
      "name": "large_human_request_spike",
      "input": "5x human request increase for one district/resource over 2 runs",
      "expected_behavior": "beta_applied rises within bounds; no direct allocation write by neural layer",
      "acceptance_criteria": [
        "0.2<=beta<=0.8",
        "knob log persisted",
        "solver input remains CSV",
        "no solver constraint changes"
      ]
    },
    {
      "id": "D2",
      "scope": "district",
      "name": "repeated_unmet_demand",
      "input": "unmet > 0 for 3 consecutive runs",
      "expected_behavior": "chronic_unmet finding and pending recommendation generated",
      "acceptance_criteria": [
        "finding_type=chronic_unmet exists",
        "recommendation status is pending",
        "no auto-apply"
      ]
    },
    {
      "id": "D3",
      "scope": "district",
      "name": "delayed_receipt_confirmations",
      "input": "receipts unconfirmed beyond 1.5x implied delay",
      "expected_behavior": "chronic_delay signal generated and recommendation created",
      "acceptance_criteria": [
        "signal count > 0",
        "incident/finding logged",
        "solver run completes 
```
*(Output truncated for brevity)*

### production_readiness_phase4_to_phase8_report.json
```json
{
  "generated_at": "2026-02-16T21:50:00Z",
  "scope": "Phase 4 through Phase 8 foundations",
  "overall_status": "PASS",
  "production_ready": true,
  "evidence": {
    "backend_consolidated": {
      "command": "pytest -q tests/test_api_endpoints_full.py tests/test_phase6_hardening.py tests/test_phase7_end_to_end_contract.py tests/test_phase7_priority_urgency_ml.py tests/test_phase8_solver_multiperiod.py tests/test_system_hardening.py",
      "result": "57 passed"
    },
    "backend_phase6_phase7_system": {
      "command": "pytest -q tests/test_phase6_hardening.py tests/test_phase7_end_to_end_contract.py tests/test_phase7_priority_urgency_ml.py tests/test_system_hardening.py",
      "result": "41 passed"
    },
    "frontend": {
      "command": "npm test",
      "result": "7 files passed, 50 tests passed"
    },
    "verification_battery": {
      "command": "python verification_battery_A_I.py",
      "result": "overall_ok=true, pass=23, fail=0",
      "report_file": "verification_battery_report.json"
    },
    "manual_suite": {
      "command": "python manual_validation_suite.py",
      "result": "52 green, 1 red",
      "note": "Single red is a stale suite expectation of 200 on /district/request; runtime contract is 201 Created and validated by maintained pytest suites."
    }
  },
  "sections": {
    "A": {
      "status": "PASS",
      "checks": {
        "A1": "PASS",
        "A2": "PASS",
        "A3": "PASS",
        "A4": "PASS",
        "A5": "PASS"
      },
  
```
*(Output truncated for brevity)*

### regression_matrix.json
```json
{
  "timestamp": "2026-02-15 14:30:00",
  "base_url": "http://localhost:8000",
  "totals": {
    "all": 50,
    "passed": 50,
    "failed": 0,
    "critical_total": 26,
    "critical_failed": 0,
    "major_total": 24,
    "major_failed": 0
  },
  "gate": {
    "critical_pass": true,
    "major_pass": true,
    "overall_green": true
  },
  "results": [
    {
      "name": "auth.login.admin",
      "severity": "critical",
      "passed": true,
      "http_status": 200,
      "detail": "{'access_token': 'c494162caf5d808a23c6c7b8161f70d563807d21d51a4262a0832333f88dabfd', 'token_type': 'bearer', 'role': 'admin', 'state_code': None, 'district_code': None}"
    },
    {
      "name": "auth.login.district",
      "severity": "critical",
      "passed": true,
      "http_status": 200,
      "detail": "{'access_token': 'f9fbfc1459eec50e867577980bde595885b16128b6ae6d1cd9dcebdb1e593dfd', 'token_type': 'bearer', 'role': 'district', 'state_code': '33', 'district_code': '603'}"
    },
    {
      "name": "auth.login.state",
      "severity": "critical",
      "passed": true,
      "http_status": 200,
      "detail": "{'access_token': '216d152b31fe2d8628cfef3852fb8fe1fa19ded5bd4e71d9e938c411748a2853', 'token_type': 'bearer', 'role': 'state', 'state_code': '33', 'district_code': None}"
    },
    {
      "name": "auth.login.national",
      "severity": "critical",
      "passed": true,
      "http_status": 200,
      "detail": "{'access_token': '78316f43068790f1c94a1df76e1d0eaae55adcd1ca72c07
```
*(Output truncated for brevity)*

### stability_evidence.json
```json
{
  "generated_at": "2026-02-21T07:49:13.729099+00:00",
  "baseline": {
    "latest_solver_runs": [
      {
        "id": 16,
        "mode": "live",
        "status": "completed",
        "started_at": "2026-02-21 07:52:23.408896"
      },
      {
        "id": 15,
        "mode": "live",
        "status": "completed",
        "started_at": "2026-02-21 07:51:09.459983"
      },
      {
        "id": 14,
        "mode": "scenario",
        "status": "completed",
        "started_at": "2026-02-21 07:50:33.686199"
      },
      {
        "id": 13,
        "mode": "scenario",
        "status": "completed",
        "started_at": "2026-02-21 07:49:56.754858"
      },
      {
        "id": 12,
        "mode": "scenario",
        "status": "completed",
        "started_at": "2026-02-21 07:49:15.887011"
      },
      {
        "id": 11,
        "mode": "live",
        "status": "failed",
        "started_at": "2026-02-21 07:40:59.232250"
      },
      {
        "id": 10,
        "mode": "live",
        "status": "failed",
        "started_at": "2026-02-21 07:35:18.139399"
      },
      {
        "id": 9,
        "mode": "live",
        "status": "failed",
        "started_at": "2026-02-21 07:34:45.221608"
      },
      {
        "id": 8,
        "mode": "live",
        "status": "completed",
        "started_at": "2026-02-21 07:20:29.339417"
      },
      {
        "id": 7,
        "mode": "live",
        "status": "completed",
        "started_at": "2026-02-21 07:19:24.036842"
```
*(Output truncated for brevity)*

### stability_matrix_results.json
```json
{
  "generated_at": "2026-02-21T02:21:19.999668+00:00",
  "baseline": {
    "recent_runs": [
      {
        "id": 208,
        "mode": "live",
        "status": "failed",
        "scenario_id": null,
        "started_at": "2026-02-21 01:30:30.694066"
      },
      {
        "id": 207,
        "mode": "live",
        "status": "failed",
        "scenario_id": null,
        "started_at": "2026-02-21 00:37:54.137888"
      },
      {
        "id": 206,
        "mode": "scenario",
        "status": "completed",
        "scenario_id": 58,
        "started_at": "2026-02-21 00:37:48.405038"
      },
      {
        "id": 205,
        "mode": "scenario",
        "status": "completed",
        "scenario_id": 57,
        "started_at": "2026-02-21 00:37:41.154939"
      },
      {
        "id": 204,
        "mode": "scenario",
        "status": "completed",
        "scenario_id": 56,
        "started_at": "2026-02-21 00:37:33.017655"
      },
      {
        "id": 203,
        "mode": "scenario",
        "status": "completed",
        "scenario_id": 55,
        "started_at": "2026-02-21 00:37:22.654027"
      },
      {
        "id": 202,
        "mode": "scenario",
        "status": "completed",
        "scenario_id": 54,
        "started_at": "2026-02-21 00:37:14.222393"
      },
      {
        "id": 201,
        "mode": "scenario",
        "status": "completed",
        "scenario_id": 53,
        "started_at": "2026-02-21 00:36:57.120046"
      },
      {
        "id": 200,
      
```
*(Output truncated for brevity)*

### STRUCTURAL_DISCOVERY_SYSTEM_MAP.json
```json
{
  "audit_type": "structural_discovery",
  "scope": {
    "workspace": "disaster_management",
    "frontend": "frontend/disaster-frontend/src",
    "backend": "backend/app",
    "mode": "read-only discovery"
  },
  "auth": {
    "backend": {
      "login_endpoint": {
        "method": "POST",
        "path": "/auth/login",
        "request": {
          "username": "string",
          "password": "string"
        },
        "response": {
          "access_token": "hex token",
          "token_type": "bearer",
          "role": "district|state|national|admin",
          "state_code": "string|null",
          "district_code": "string|null"
        }
      },
      "token_model": {
        "format": "32-byte hex token via secrets.token_hex(32)",
        "transport": "Authorization: Bearer <token>",
        "storage": [
          "in-memory TOKEN_STORE",
          "SQLite table auth_tokens(token,payload,created_at)"
        ],
        "expiry": "no explicit TTL/expiry claims",
        "refresh_flow": "none"
      },
      "authorization": {
        "mechanism": "require_role([...]) over decoded payload role",
        "failure_codes": {
          "401": [
            "invalid header format",
            "invalid token format",
            "missing token payload"
          ],
          "403": [
            "role not allowed"
          ]
        }
      }
    },
    "frontend": {
      "session_store": {
        "localStorage_keys": [
          "user",
          "token"
        ]
 
```
*(Output truncated for brevity)*

### ui_audit_results.json
```json
{
  "started_at": "2026-03-01T15:59:05.296382+00:00",
  "config": {
    "frontend_base": "http://127.0.0.1:5173",
    "api_base": "http://127.0.0.1:8000",
    "headless": false,
    "slow_mo": 150,
    "target_district_code": "603",
    "target_state_code": "33"
  },
  "role_matrix": {
    "district": {
      "logged_in": true,
      "username": "district_603",
      "redirect_ok": true,
      "console_error_count": 1,
      "http_error_count": 0,
      "state_code": "33",
      "district_code": "603"
    },
    "state": {
      "logged_in": true,
      "username": "state_33",
      "redirect_ok": true,
      "console_error_count": 1,
      "http_error_count": 0,
      "state_code": "33",
      "district_code": null
    },
    "national": {
      "logged_in": true,
      "username": "national_admin",
      "redirect_ok": true,
      "console_error_count": 1,
      "http_error_count": 0,
      "state_code": null,
      "district_code": null
    },
    "admin": {
      "logged_in": false,
      "username": null,
      "redirect_ok": false,
      "console_error_count": 1,
      "http_error_count": 0,
      "error": "Login failed for role=admin. Attempts: admin: Login timed out; current_url=http://127.0.0.1:5173/login | admin_user: Login timed out; current_url=http://127.0.0.1:5173/login | verify_admin: Login timed out; current_url=http://127.0.0.1:5173/login"
    }
  },
  "district_tests": {},
  "state_tests": {},
  "national_tests": {},
  "admin_tests": {},
  "invariant_violati
```
*(Output truncated for brevity)*

### UI_STRICT_MASS_CERT_REPORT.json
```json
{
  "started_at": "2026-03-03T01:42:19.862351+00:00",
  "config": {
    "frontend_base": "http://127.0.0.1:5173",
    "api_base": "http://127.0.0.1:8000",
    "district_runs_target": 1,
    "admin_runs_target": 1,
    "dashboard_checks_target": 2,
    "overall_target": 4,
    "headless": true,
    "slow_mo": 40
  },
  "district_runs": [],
  "admin_runs": [],
  "dashboard_checks": [],
  "pool_rollup_check": {},
  "auto_escalation_check": {},
  "priority_time_analysis": {},
  "errors": [
    {
      "stage": "fatal",
      "error": "UI login failed for role=admin; attempts=['admin: no redirect/token (url=http://127.0.0.1:5173/login)', 'admin_user: no redirect/token (url=http://127.0.0.1:5173/login)', 'verify_admin: no redirect/token (url=http://127.0.0.1:5173/login)']"
    }
  ],
  "finished_at": "2026-03-03T01:44:49.392405+00:00",
  "summary": {
    "total_tests": 0,
    "passed_tests": 0,
    "failed_tests": 0,
    "district_runs": 0,
    "admin_runs": 0,
    "dashboard_checks": 0
  }
}
```
### verification_battery_report.json
```json
{
  "summary": {
    "total": 23,
    "pass": 23,
    "fail": 0,
    "overall_ok": true
  },
  "hard_requirements": {
    "all_A_to_D_pass": true,
    "B2_pass": true,
    "C2_pass": true,
    "I1_pass": true
  },
  "category_totals": {
    "A": {
      "pass": 3,
      "fail": 0
    },
    "B": {
      "pass": 2,
      "fail": 0
    },
    "C": {
      "pass": 3,
      "fail": 0
    },
    "D": {
      "pass": 4,
      "fail": 0
    },
    "E": {
      "pass": 2,
      "fail": 0
    },
    "F": {
      "pass": 3,
      "fail": 0
    },
    "G": {
      "pass": 2,
      "fail": 0
    },
    "H": {
      "pass": 2,
      "fail": 0
    },
    "I": {
      "pass": 2,
      "fail": 0
    }
  },
  "results": [
    {
      "id": "A1",
      "status": "PASS",
      "evidence": "run_id=172, final_demand_rows=55",
      "root_cause": null,
      "minimal_fix": null
    },
    {
      "id": "A2",
      "status": "PASS",
      "evidence": "scenario_id=38, run_ids=(173,174) deterministic",
      "root_cause": null,
      "minimal_fix": null
    },
    {
      "id": "A3",
      "status": "PASS",
      "evidence": "human_only_run=175, baseline_only_run=176, human_rows=0 enforced",
      "root_cause": null,
      "minimal_fix": null
    },
    {
      "id": "B1",
      "status": "PASS",
      "evidence": "latest_run=121, prev_run=119, state_summary_run=121, national_summary_run=121",
      "root_cause": null,
      "minimal_fix": null
    },
    {
      "id": "B2",
      "status": "PASS",
 
```
*(Output truncated for brevity)*

### verification_report_phase4_to_phase9_full.json
```json
{
  "timestamp_utc": "2026-02-17T20:05:00Z",
  "project": "Disaster Decision Intelligence Platform",
  "overall": {
    "backend_tests": {
      "status": "pass",
      "command": "python -m unittest discover -s backend/tests -p test_*.py",
      "result": "62 tests passed"
    },
    "frontend_tests": {
      "status": "pass",
      "command": "npm run test (frontend/disaster-frontend)",
      "result": "7 files, 50 tests passed"
    },
    "frontend_build": {
      "status": "pass",
      "command": "npm run build (frontend/disaster-frontend)",
      "result": "vite build successful"
    }
  },
  "sections": {
    "A": {
      "name": "Frontend Global Checklist",
      "status": "partial",
      "evidence": [
        "Frontend test suite passed (50 tests)",
        "Frontend production build passed"
      ],
      "notes": "Runtime browser-click verification for spinner/tooltip/pagination/sort/search per page requires dedicated E2E runner instrumentation."
    },
    "B": {
      "name": "District Dashboard Buttons",
      "status": "partial",
      "evidence": [
        "API endpoints tested in backend/tests/test_api_endpoints_full.py",
        "District route/navigation tests passed"
      ],
      "notes": "Automated backend contract checks pass; full click-by-click UI interaction validation still requires browser E2E automation."
    },
    "C": {
      "name": "District to State Escalation",
      "status": "pass",
      "evidence": [
        "State escalation endpoint
```
*(Output truncated for brevity)*

### DISTRICT603_LIVE_CAMPAIGN_RERUN_2026-03-02.txt
```text

```
### STRESS_20_INVARIANTS_RERUN3_2026-03-02.txt
```text

```
