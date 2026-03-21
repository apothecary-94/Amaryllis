# Distribution Resilience Report

## Purpose
`P4-D03` introduces a consolidated distribution-path report for Linux primary channel:
- parity smoke surface,
- installer/upgrade checks,
- rollback safety checks.

Script:
- `scripts/release/build_distribution_resilience_report.py`

Example:

```bash
python scripts/release/build_distribution_resilience_report.py \
  --linux-parity-report artifacts/linux-parity-smoke-report.json \
  --linux-installer-report artifacts/linux-installer-smoke-report.json \
  --output artifacts/distribution-resilience-report.json
```

## Inputs

Required:
- `artifacts/linux-parity-smoke-report.json`
- `artifacts/linux-installer-smoke-report.json`

Optional:
- `artifacts/runtime-lifecycle-smoke-report.json`

## Output

Default:
- `artifacts/distribution-resilience-report.json`

Suite id:
- `distribution_resilience_report_v1`

## Contract Summary

Report includes:
- `sources` metadata (suite/path/generated_at),
- normalized `checks[]` (pass/fail with thresholds),
- extracted `kpis`,
- `summary` (`checks_total`, `checks_passed`, `checks_failed`, `score_pct`, `status`).

Failure conditions include:
- non-zero parity error rate or failed parity checks,
- failed installer/rollback required checks,
- failed command return codes in installer smoke,
- optional runtime lifecycle failures when source is provided.

Exit codes:
- `0`: all checks passed
- `1`: report generated but at least one blocking check failed
- `2`: missing/invalid source report

## CI Integration

`release-gate.yml` (Linux parity stage):
- runs builder as blocking gate,
- uploads `artifacts/distribution-resilience-report.json` artifact.
