# Model Package Catalog

## Purpose
`P4-H02` introduces a package-level model catalog so users can choose models by capability and system fit, not by raw artifact ids.

## Endpoints
- `GET /models/packages`
  - query: `profile`, `include_remote_providers`, `limit`
  - returns package catalog with:
    - package identity (`package_id = <provider>::<model>`)
    - quality/speed tiers, tags, estimated size
    - runtime memory requirements
    - compatibility fit against detected hardware
    - `license_admission` status (`allow` / `allow_with_warning` / `deny`)
    - one-click install contract payload (`/models/packages/install`)
- `POST /models/packages/install`
  - body: `{"package_id":"<provider>::<model>", "activate": true|false}`
  - executes package install flow:
    - license admission preflight (blocks install when policy denies)
    - download step (when provider supports download and model is not installed)
    - activate step (`/models/load`) when `activate=true`

## Catalog Semantics
- `selected_profile` controls package ranking (`fast`, `balanced`, `quality`).
- `recommended_profile` is derived from onboarding hardware heuristic.
- `profiles[*].top_package_ids` provides profile-oriented shortlists for UI.

## Contract Notes
- Package install flow is idempotent for already-installed local models (download is skipped).
- For remote providers without download support, install skips download and only activates route target.
- License policy is loaded from `policies/license/default.json` (override path: `AMARYLLIS_LICENSE_POLICY_PATH`).
- Strict metadata mode is configurable via `AMARYLLIS_LICENSE_ADMISSION_REQUIRE_METADATA` (default: `false`).
- `catalog_version` is currently `model_package_catalog_v1`.

## Test Coverage
- `tests/test_model_package_catalog.py`
- `tests/test_model_package_catalog_api.py`
- `tests/test_cognition_backends.py`
- `tests/test_cognition_backend_runtime.py`
