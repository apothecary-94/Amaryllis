# Model Onboarding Profiles

## Purpose
`GET /models/onboarding/profile` provides first-run profile recommendation for model routing.

The goal is to get a new user to the first successful response without manual model tuning.

## Contract
Response fields:
- `generated_at`: UTC timestamp.
- `request_id`: request correlation id from runtime middleware.
- `active`: currently active provider/model pair.
- `hardware`: runtime-detected machine snapshot (`platform`, `machine`, `cpu_count_logical`, `memory_bytes`, `memory_gb`, provider availability flags).
- `recommended_profile`: one of `fast`, `balanced`, `quality`.
- `reason_codes`: machine-readable reason labels for the recommendation.
- `profiles`: profile map for `fast`, `balanced`, `quality` with:
  - `route_mode` (`local_first`, `balanced`, `quality_first`)
  - routing constraints
  - selected model target
  - fallback candidates

## Recommendation Logic (MVP)
- `fast`: selected for low-memory/low-CPU machines.
- `quality`: selected for high-compute machines (and/or cloud-capable setups).
- `balanced`: default profile otherwise.

Profile targets are selected from the same candidate matrix used by routing (`ModelManager`), with provider guardrail penalties applied.

## Deterministic Backend
`DeterministicCognitionBackend` returns a stable onboarding payload with `recommended_profile=balanced` for contract/runtime tests.

## Test Coverage
- `tests/test_model_onboarding_profile.py`
- `tests/test_model_onboarding_profile_api.py`
- `tests/test_cognition_backends.py`
- `tests/test_cognition_backend_runtime.py`
