# License Admission Gate

`scripts/release/license_admission_gate.py` validates SPDX license admission policy for onboarding.

The suite checks:
- allow-listed SPDX license is admitted,
- share-alike allow-listed license is admitted,
- denied SPDX license is rejected,
- non-commercial flag is rejected,
- no-derivatives flag is rejected,
- unknown SPDX identifier is rejected.

Policy source:
- `policies/license/default.json`
- override path via `AMARYLLIS_LICENSE_POLICY_PATH`

## Run Locally

```bash
python scripts/release/license_admission_gate.py \
  --min-admission-score-pct 100 \
  --max-failed-scenarios 0 \
  --require-scenario allowed_license_admitted \
  --require-scenario denied_spdx_rejected \
  --require-scenario noncommercial_rejected \
  --output artifacts/license-admission-report.json
```

## Gate Output

Report `license_admission_gate_v1` contains:
- `summary.admission_score_pct`
- `summary.failed_scenarios`
- `summary.errors`
- `policy.id` + `policy.path`
- per-scenario expected vs observed admission status
