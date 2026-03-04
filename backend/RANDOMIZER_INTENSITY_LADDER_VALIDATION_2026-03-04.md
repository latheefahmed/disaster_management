# Randomizer Intensity Ladder Validation (2026-03-04)

- Levels tested: 7
- Passed: 7
- Failed: 0

| Level | Scenario | Run | Ratio(actual/expected) | Supply | Demand | Unmet | StateUsed | NationalUsed | NeighborAlloc | Pass |
|---|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| extremely_low | 310 | 1089 | 0.200/0.20 | 58774597636.00 | 11754919527.20 | 0.00 | True | True | 0.00 | PASS |
| low | 311 | 1090 | 0.400/0.40 | 58774597636.00 | 23509839054.40 | 0.00 | True | True | 0.00 | PASS |
| medium_low | 312 | 1091 | 0.700/0.70 | 58774597636.00 | 41142218345.20 | 0.00 | True | True | 0.00 | PASS |
| medium | 313 | 1092 | 1.000/1.00 | 58774597636.00 | 58774597636.00 | 0.00 | True | True | 0.00 | PASS |
| medium_high | 314 | 1093 | 1.250/1.25 | 58774597636.00 | 73468247045.00 | 38969784.00 | True | True | 0.00 | PASS |
| high | 315 | 1094 | 1.500/1.50 | 58774597636.00 | 88161896454.00 | 174619094.00 | True | True | 0.00 | PASS |
| extremely_high | 316 | 1095 | 1.790/1.79 | 58774597636.00 | 105206529768.44 | 80426480.00 | True | True | 0.00 | PASS |