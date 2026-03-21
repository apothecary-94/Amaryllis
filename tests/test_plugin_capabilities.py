from __future__ import annotations

import unittest
from typing import Any

from tools.plugin_capabilities import (
    default_allowed_plugin_capabilities,
    plugin_capability_policy_snapshot,
    validate_plugin_manifest_capabilities,
)


def _manifest(*, capabilities: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": "example_plugin",
        "version": "1.0.0",
        "capabilities": list(capabilities or ["filesystem_read"]),
    }


class PluginCapabilitiesTests(unittest.TestCase):
    def test_policy_snapshot_contains_expected_defaults(self) -> None:
        snapshot = plugin_capability_policy_snapshot()
        self.assertIn("capabilities", snapshot)
        self.assertIn("filesystem_read", snapshot["capabilities"])
        self.assertIn("filesystem_write", snapshot["capabilities"])
        self.assertIn("network", snapshot["capabilities"])
        self.assertIn("process", snapshot["capabilities"])
        self.assertEqual(snapshot["default_allowed_capabilities"], default_allowed_plugin_capabilities())
        self.assertIn("process", snapshot["blocked_capabilities"])

    def test_validate_accepts_supported_capabilities(self) -> None:
        result = validate_plugin_manifest_capabilities(
            manifest=_manifest(capabilities=["filesystem_read", "filesystem_write"]),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "capability_contract_ok")
        self.assertEqual(result.capabilities, ("filesystem_read", "filesystem_write"))

    def test_validate_rejects_missing_capabilities(self) -> None:
        result = validate_plugin_manifest_capabilities(
            manifest={"name": "x", "version": "1.0.0"},
        )
        self.assertFalse(result.ok)
        self.assertIn("must be a non-empty array", result.reason)

    def test_validate_rejects_unknown_capability(self) -> None:
        result = validate_plugin_manifest_capabilities(
            manifest=_manifest(capabilities=["filesystem_read", "root"]),
        )
        self.assertFalse(result.ok)
        self.assertIn("unsupported values: root", result.reason)

    def test_validate_rejects_blocked_process_capability(self) -> None:
        result = validate_plugin_manifest_capabilities(
            manifest=_manifest(capabilities=["filesystem_read", "process"]),
        )
        self.assertFalse(result.ok)
        self.assertIn("blocked values: process", result.reason)

    def test_validate_rejects_write_without_read(self) -> None:
        result = validate_plugin_manifest_capabilities(
            manifest=_manifest(capabilities=["filesystem_write"]),
        )
        self.assertFalse(result.ok)
        self.assertIn("requires 'filesystem_read'", result.reason)


if __name__ == "__main__":
    unittest.main()
