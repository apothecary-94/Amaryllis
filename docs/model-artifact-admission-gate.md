# Model Artifact Admission Gate

`scripts/release/model_artifact_admission_gate.py` validates secure model package admission, quant passport policy, and license admission policy.

The suite checks:
- valid signed manifest with hash + quant metadata,
- missing quant recipe rejection,
- signature mismatch rejection,
- artifact hash mismatch rejection,
- non-managed trust level rejection in strict mode,
- denied SPDX license rejection (license policy).

License policy source:
- `policies/license/default.json`
- override path via `AMARYLLIS_LICENSE_POLICY_PATH`

## Run Locally

```bash
python scripts/release/model_artifact_admission_gate.py \
  --min-admission-score-pct 100 \
  --max-failed-scenarios 0 \
  --require-scenario valid_manifest_admitted \
  --require-scenario missing_quant_recipe_rejected \
  --require-scenario denied_license_rejected \
  --output artifacts/model-artifact-admission-report.json
```

## Gate Output

Report `model_artifact_admission_gate_v1` contains:
- `summary.admission_score_pct`
- `summary.failed_scenarios`
- `summary.errors`
- `quantization_reference` (recipe/method/bits/converter metadata extracted from the canonical passing scenario)
- per-scenario expected vs observed admission status (`observed.summary` includes license policy/admission details)
