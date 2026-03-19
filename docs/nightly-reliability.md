# Nightly Extended Reliability Run

## Purpose

Nightly run validates non-functional reliability regressions and publishes a machine-readable report with trend deltas for:
- success rate,
- latency (p95),
- stability (latency jitter + stability score).

## Workflow

- GitHub Actions: `.github/workflows/nightly-reliability.yml`
- Triggers:
  - nightly schedule (`cron: 0 2 * * *`, UTC),
  - manual dispatch.

## Local Run

```bash
python3 scripts/release/nightly_reliability_run.py \
  --iterations 12 \
  --min-success-rate-pct 99 \
  --max-p95-latency-ms 600 \
  --max-latency-jitter-ms 120 \
  --baseline eval/baselines/reliability/nightly_smoke_baseline.json \
  --strict
```

## Report

Default output path:

```text
eval/reports/reliability/nightly_<timestamp>.json
```

Workflow output artifact:

```text
artifacts/nightly-reliability-report.json
```

Report includes:
- `summary`: total/failed requests, success/error rate, avg/p95 latency, jitter, stability score.
- `trend_deltas`: deltas vs baseline metrics.
- `failures`: per-request mismatch details (expected vs actual status, round, latency).

## Baseline

Baseline file:

```text
eval/baselines/reliability/nightly_smoke_baseline.json
```

Used for trend deltas only. Strict pass/fail is governed by explicit threshold flags/env vars.
