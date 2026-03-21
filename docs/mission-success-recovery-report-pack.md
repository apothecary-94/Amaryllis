# Mission Success/Recovery Report Pack

## Purpose
`P3-D02` provides a public KPI report pack for mission success and recovery signals across
release and nightly pipelines.

Script:
- `scripts/release/build_mission_success_recovery_report.py`

## Output

Default output:
- `artifacts/mission-success-recovery-report.json`

Nightly output:
- `artifacts/nightly-mission-success-recovery-report.json`

Suite id:
- `mission_success_recovery_report_pack_v1`

## Supported Sources

Release scope:
- mission queue load gate report
- fault-injection reliability report
- release quality dashboard snapshot
- user journey benchmark report

Nightly scope:
- nightly reliability report
- nightly burn-rate gate report
- nightly user journey benchmark report

The script accepts any subset and produces a normalized report with:
- source metadata
- extracted KPI values
- normalized pass/fail checks (`gte` / `lte`)
- summary status (`pass` / `fail`)

Optional user-flow source flag:
- `--user-journey-report <path>`

## CI Integration

- Release workflow (`release-gate.yml`) exports:
  - `artifacts/mission-success-recovery-report.json`
- Nightly workflow (`nightly-reliability.yml`) exports:
  - `artifacts/nightly-mission-success-recovery-report.json`

This makes mission reliability KPIs available as machine-readable artifacts for each release and nightly run.
