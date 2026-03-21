# User Journey Benchmark

## Purpose
`P4-D01` introduces an end-to-end benchmark for the primary product loop:

`intent -> flow session -> planning mode -> execute mode -> review`.

Script:
- `scripts/release/user_journey_benchmark.py`

## Outputs

Release output:
- `artifacts/user-journey-benchmark-report.json`

Nightly output:
- `artifacts/nightly-user-journey-benchmark-report.json`

Baseline:
- `eval/baselines/quality/user_journey_benchmark_baseline.json`

Suite id:
- `user_journey_benchmark_v1`

## KPI Surface

The report captures:
- `journey_success_rate_pct`
- `p95_journey_latency_ms`
- `p95_plan_dispatch_latency_ms`
- `p95_execute_dispatch_latency_ms`
- `plan_to_execute_conversion_rate_pct`

Each run also emits normalized checks (`gte` / `lte`) against configured thresholds,
plus trend deltas versus optional baseline metrics.

## CI Integration

- `release-gate.yml`
  - runs strict user journey benchmark gate,
  - uploads `artifacts/user-journey-benchmark-report.json`,
  - feeds the report into mission success/recovery pack.
- `nightly-reliability.yml`
  - runs strict nightly user journey benchmark,
  - uploads `artifacts/nightly-user-journey-benchmark-report.json`,
  - feeds the report into nightly mission success/recovery pack.
