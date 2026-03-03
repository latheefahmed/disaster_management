# SINGLE DISTRICT ESCALATION REPORT

Generated: 2026-02-22T09:08:45.033648Z
District: 603
Parent State: 33
Neighbor State: 1

## Final Verdict

- Verdict: **PASS**

| Phase | Name | Verdict |
|---|---|---|
| P0 | Clean slate reset | PASS |
| P1 | Class rule enforcement | PASS |
| P2 | Source pool tracking schema | PASS |
| P3 | Forced shortage setup | PASS |
| P4 | Request + solver run escalation chain | PASS |
| P5 | Consumable flow | PASS |
| P6 | Non-consumable return flow | PASS |
| P7 | Escalation UI verification (code-level) | PASS |

## Initial Stock Layout

```json
{
  "district": {
    "R5": 0.0,
    "R8": 0.0,
    "R41": 0.0
  },
  "state": {
    "R5": 500000000.0,
    "R8": 0.0,
    "R41": 0.0
  },
  "neighbor_state": {
    "R5": 0.0,
    "R8": 5000000.0,
    "R41": 0.0
  },
  "national": {
    "R5": 0.0,
    "R8": 0.0,
    "R41": 5000000.0
  }
}
```

## Requests

```json
{
  "time": 0,
  "rows": [
    {
      "resource_id": "R5",
      "quantity": 100.0
    },
    {
      "resource_id": "R8",
      "quantity": 1.0
    },
    {
      "resource_id": "R41",
      "quantity": 1.0
    }
  ]
}
```

## Allocation Sources

```json
{
  "R5": {
    "allocated": 400.19392,
    "source_scope": "state",
    "source_code": "33",
    "supply_level": "state",
    "origin_state_code": "33"
  },
  "R8": {
    "allocated": 4.1034243,
    "source_scope": "neighbor_state",
    "source_code": "1",
    "supply_level": "state",
    "origin_state_code": "1"
  },
  "R41": {
    "allocated": 1.0,
    "source_scope": "national",
    "source_code": "NATIONAL",
    "supply_level": "national",
    "origin_state_code": "NATIONAL"
  }
}
```

## Consume/Return Results

```json
{
  "phase5": {
    "consume_performed": true,
    "consume_error": "",
    "c1_available": 400.19392,
    "return_blocked": true,
    "return_error": "Resource 'R5' is non-returnable and cannot be added to pool"
  },
  "phase6": {
    "checks": {
      "n1_origin_pool_increased": true,
      "n2_origin_pool_increased": true,
      "district_n1_unchanged": true,
      "district_n2_unchanged": true
    },
    "n1_available": 4.1034243,
    "n2_available": 1.0,
    "pool_before": {
      "neighbor_n1": 0.0,
      "national_n2": 0.0
    },
    "pool_after": {
      "neighbor_n1": 1.0,
      "national_n2": 1.0
    },
    "district_stock_before": {
      "N1": 0.0,
      "N2": 0.0
    },
    "district_stock_after": {
      "N1": 0.0,
      "N2": 0.0
    },
    "run_id": 1
  },
  "context": {
    "run_id": 1
  }
}
```

## Bugs Found

- Source scope/code fields were not explicit in allocation schema and ingest output.
- Canonical class policy did not expose explicit can_consume/can_return fields.

## Fixes Applied

- Added canonical can_consume/can_return and normalized class_type to consumable/non_consumable.
- Added allocation_source_scope and allocation_source_code to allocations + ingest + UI column.
- Hardened pool allocate APIs with canonical + policy validation.

## Why This Won't Regress

- Added lifecycle regression tests for consume/return policy and ingest source fields.
- Runtime migrations backfill source scope/code and policy flags on existing databases.
