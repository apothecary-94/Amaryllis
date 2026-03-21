from __future__ import annotations

import unittest
from typing import Any

from tools.plugin_compat import (
    PLUGIN_COMPAT_MANIFEST_VERSION,
    PLUGIN_REGISTRY_API_VERSION,
    plugin_compat_contract_snapshot,
    validate_plugin_manifest_compat,
)


def _manifest(*, runtime_modes: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": "example_plugin",
        "version": "1.2.3",
        "compat": {
            "manifest_version": PLUGIN_COMPAT_MANIFEST_VERSION,
            "tool_registry_api": PLUGIN_REGISTRY_API_VERSION,
            "runtime_modes": list(runtime_modes or ["sandboxed", "legacy"]),
        },
        "tool": {
            "name": "example_tool",
            "description": "Compatibility test tool",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
            "entrypoint": "execute",
        },
    }


class PluginCompatTests(unittest.TestCase):
    def test_contract_snapshot_has_expected_versions(self) -> None:
        snapshot = plugin_compat_contract_snapshot()
        self.assertEqual(snapshot["manifest_version"], PLUGIN_COMPAT_MANIFEST_VERSION)
        self.assertEqual(snapshot["tool_registry_api"], PLUGIN_REGISTRY_API_VERSION)
        self.assertEqual(snapshot["allowed_runtime_modes"], ["legacy", "sandboxed"])

    def test_validator_accepts_supported_manifest(self) -> None:
        result = validate_plugin_manifest_compat(
            manifest=_manifest(),
            runtime_mode="sandboxed",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "compatibility_contract_ok")

    def test_validator_rejects_missing_compat(self) -> None:
        manifest = _manifest()
        manifest.pop("compat", None)
        result = validate_plugin_manifest_compat(
            manifest=manifest,
            runtime_mode="sandboxed",
        )
        self.assertFalse(result.ok)
        self.assertIn("field 'compat' must be an object", result.reason)

    def test_validator_rejects_unsupported_manifest_version(self) -> None:
        manifest = _manifest()
        compat = manifest.get("compat")
        assert isinstance(compat, dict)
        compat["manifest_version"] = "v9"
        result = validate_plugin_manifest_compat(
            manifest=manifest,
            runtime_mode="sandboxed",
        )
        self.assertFalse(result.ok)
        self.assertIn("unsupported compat.manifest_version", result.reason)

    def test_validator_rejects_runtime_mismatch(self) -> None:
        result = validate_plugin_manifest_compat(
            manifest=_manifest(runtime_modes=["legacy"]),
            runtime_mode="sandboxed",
        )
        self.assertFalse(result.ok)
        self.assertIn("runtime compatibility mismatch", result.reason)

    def test_validator_rejects_unknown_runtime_mode(self) -> None:
        result = validate_plugin_manifest_compat(
            manifest=_manifest(runtime_modes=["sandboxed", "gpu"]),
            runtime_mode="sandboxed",
        )
        self.assertFalse(result.ok)
        self.assertIn("unsupported values: gpu", result.reason)


if __name__ == "__main__":
    unittest.main()
