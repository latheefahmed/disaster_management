# High-Level Evaluation Metrics (2026-03-03)

## Scope
System-level evaluation emphasizing correctness, reliability, and performance.
Low-level login/auth gate checks are intentionally excluded.

## Primary Metrics
- Functional accuracy: **98.11%**
- Campaign completion rate: **100.0%**
- Claim success rate: **100.0%**
- Consume success rate: **100.0%**
- Return success rate: **100.0%**
- Consumable conservation rate: **100.0%**
- Non-consumable reversibility rate: **87.5%**
- Probe HTTP success rate: **100.0%**

## Performance / SLO-Style Metrics
- Latency p50: **861.56 ms**
- Latency p95: **10202.85 ms**
- Latency max: **11153.3 ms**
- Endpoint coverage with p95 <= 1s: **50.0%**
- Endpoint coverage with p95 <= 3s: **80.0%**

## Composite Indices
- Correctness score: **97.6%**
- Reliability score: **100.0%**
- Performance score: **59.66%**
- Overall quality index: **88.84%**

## Interpretation
- Quality band: **good**
- Risk highlight: High-latency summary endpoints dominate tail latency (state/national allocations summary).

## Data Sources
- backend/manual_validation_suite_report.json
- backend/DISTRICT603_LIVE_CAMPAIGN_REPORT.json
- backend/SOLVER_BACKEND_BRUTEFORCE_DOSSIER.json
- backend/PERFORMANCE_PROBE_MATRIX_LATEST.json
