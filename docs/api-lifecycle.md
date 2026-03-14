# API Lifecycle Policy

## Versioning

- Stable API prefix: `/v1`
- Current stable version header: `X-Amaryllis-API-Version`
- Release channel header: `X-Amaryllis-Release-Channel` (`alpha|beta|stable`)

## Backward Compatibility

Amaryllis maintains compatibility for the declared `/v1` contract file:

- `contracts/api_compat_v1.json`

Every release must pass:

- `python scripts/release/api_compat_gate.py`

If a route/method required by the contract is removed or its required request fields/status map changes, the gate fails.

## Deprecation

Legacy unversioned endpoints remain available during migration, but include:

- `Deprecation: true`
- `Sunset: <RFC7231 date>`
- `Link: </docs/api-lifecycle>; rel="deprecation"`

Migration rule:

1. Use `/v1/*` endpoints for all new clients.
2. Treat unversioned routes as transitional only.

