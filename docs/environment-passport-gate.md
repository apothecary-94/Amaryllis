# Environment Passport Gate

`scripts/release/environment_passport_gate.py` builds a reproducibility passport and enforces completeness thresholds for release/nightly artifacts.

## Purpose
- produce a machine-readable environment passport (`host/runtime/toolchain/quantization`),
- attach runtime profile + SLO profile metadata to release evidence,
- fail gate when required passport fields are missing.

## Inputs
- runtime profiles: `runtime/profiles/*.json`
- SLO profiles: `slo_profiles/*.json`
- toolchain manifest: `runtime/toolchains/core.json`
- optional model admission report:
  - `artifacts/model-artifact-admission-report.json`
  - if present, `quantization_reference` is used as passport quant metadata source.

## Output Contract
- `suite`: `environment_passport_gate_v1`
- `passport.schema_version`: `amaryllis.environment_passport.v1`
- `passport` sections:
  - `repository` (commit/branch/dirty),
  - `host` (OS, architecture, CPU/memory),
  - `runtime` (python + runtime/SLO profile manifests),
  - `toolchain` (manifest version and CI/toolchain hints),
  - `dependencies_lock` (`requirements.lock` digest),
  - `quantization` (recipe/method/bits/converter/version + source),
  - `drivers` (best-effort CUDA/ROCm/Metal env metadata).
- `summary`:
  - `completeness_score_pct`,
  - `missing_required_fields_count`,
  - `min_completeness_score_pct`,
  - `max_missing_required`,
  - `status` (`pass`/`fail`).

## CLI

```bash
python scripts/release/environment_passport_gate.py \
  --model-artifact-admission-report artifacts/model-artifact-admission-report.json \
  --min-completeness-score-pct 100 \
  --max-missing-required 0 \
  --output artifacts/environment-passport-report.json
```

## CI Wiring
- release gate:
  - runs after model artifact admission gate,
  - uploads `environment-passport-report` artifact,
  - feeds report into `build_quality_dashboard_snapshot.py`.
- nightly reliability:
  - runs nightly environment passport gate,
  - uploads `nightly-environment-passport-report` artifact.
