# Plugin Capability Policy

## Purpose
`P3-C02` adds a capability isolation matrix and policy gates for plugin actions.

Core modules:
- `tools/plugin_capabilities.py` (capability schema + matrix)
- `tools/tool_registry.py` (manifest capability validation during discovery)
- `tools/policy.py` (runtime capability policy checks)
- `tools/sandbox_runner.py` + `tools/sandbox_worker.py` (capability-bound sandbox limits)

## Manifest Field

Plugin manifest must declare top-level `capabilities`:

```json
{
  "name": "example_plugin",
  "version": "1.0.0",
  "compat": {
    "manifest_version": "v1",
    "tool_registry_api": "v1",
    "runtime_modes": ["sandboxed", "legacy"]
  },
  "capabilities": ["filesystem_read", "filesystem_write"]
}
```

Validation rules:
- `capabilities` must be a non-empty array.
- Supported values: `filesystem_read`, `filesystem_write`, `network`, `process`.
- `process` is blocked by contract (sandbox subprocess execution is disabled).
- `filesystem_write` requires `filesystem_read`.

## Capability Matrix

- `filesystem_read`
  - default allowed
  - no extra approval requirement
  - sandbox-scoped to allowed roots
- `filesystem_write`
  - default allowed
  - requires approval by policy layer
  - write remains bounded by allowed roots and policy write toggle
- `network`
  - default blocked by policy
  - requires explicit policy allow and sandbox network opt-in
- `process`
  - blocked by capability contract

## Discovery + Runtime Gates

Discovery fail-fast:
- incompatible capability manifests are blocked with:
  - `reason`: `capability_incompatible:<reason>`
  - `capability_state`: `incompatible`

Runtime policy:
- plugin tools must carry declared `execution_target.capabilities`
- policy blocks undeclared/blocked/not-allowed capabilities
- `filesystem_write` can be globally disabled (`filesystem_allow_write=false`)
- capability-driven approval requirements are merged with risk/approval policy

Sandbox enforcement:
- plugin network access is enabled only when capability + allowlist both permit it
- plugin filesystem writes are disabled unless `filesystem_write` capability is present
- guard now intercepts `builtins.open`, `io.open`, and `Path.open`

## Discovery Report Additions

`ToolRegistry.plugin_discovery_report()` now includes:
- `capability_policy` (matrix snapshot)
- `capability_summary`
- per-event `capability_state` and `capability_reason`

## Tests

- `tests/test_plugin_capabilities.py`
- `tests/test_tool_plugin_signing.py`
- `tests/test_tool_isolation_policy.py`
- `tests/test_tool_sandbox.py`
