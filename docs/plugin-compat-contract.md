# Plugin Compatibility Contract

## Purpose
`P3-C01` defines a versioned compatibility contract for plugin manifests to guarantee
upgrade-safe plugin discovery.

Validator implementation:
- `tools/plugin_compat.py`

Registry enforcement:
- `tools/tool_registry.py` (`discover_plugins`)

Related capability policy (P3-C02):
- `docs/plugin-capability-policy.md`

## Manifest Contract (`compat`)

Each plugin manifest must include:

```json
{
  "name": "example_plugin",
  "version": "1.0.0",
  "compat": {
    "manifest_version": "v1",
    "tool_registry_api": "v1",
    "runtime_modes": ["sandboxed", "legacy"]
  }
}
```

Rules:
- `compat` must be an object.
- `compat.manifest_version` must equal `v1`.
- `compat.tool_registry_api` must equal `v1`.
- `compat.runtime_modes` must be non-empty.
- runtime modes must be from: `sandboxed`, `legacy`.
- current registry runtime mode must be listed in `compat.runtime_modes`.

## Fail-Fast Behavior

Plugin discovery now validates `compat` before signature verification and before loading code.
Incompatible manifests are blocked with:

- `status`: `blocked`
- `reason`: `compat_incompatible:<validator_reason>`
- `signature_state`: `not_checked`
- `compat_state`: `incompatible`

This avoids loading plugins that target incompatible registry/runtime contracts.

## Discovery Report

`ToolRegistry.plugin_discovery_report()` now includes:

- `compat_contract`: current contract snapshot (version + allowed runtime modes)
- `compat_summary`: aggregate counts by compatibility state
- per-event `compat_state` and `compat_reason`

## Tests

- `tests/test_plugin_compat.py` (contract validator)
- `tests/test_tool_plugin_signing.py` (discovery behavior and report integration)
