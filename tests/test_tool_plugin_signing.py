from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tools.plugin_compat import PLUGIN_COMPAT_MANIFEST_VERSION, PLUGIN_REGISTRY_API_VERSION
from tools.tool_registry import ToolRegistry


PLUGIN_TOOL_CODE = """
def execute(arguments, context=None):
    ctx = context or {}
    return {
        'ok': True,
        'arguments': arguments,
        'user_id': ctx.get('user_id'),
    }
""".strip()


class ToolPluginSigningTests(unittest.TestCase):
    def test_strict_mode_blocks_unsigned_plugin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-plugin-signing-") as tmp:
            plugins_dir = Path(tmp)
            self._write_plugin(
                plugins_dir=plugins_dir,
                plugin_dir_name="unsigned",
                manifest=self._manifest("unsigned_tool"),
            )

            registry = ToolRegistry(plugin_signing_key="secret", plugin_signing_mode="strict")
            registry.discover_plugins(plugins_dir)

            self.assertNotIn("unsigned_tool", registry.names())
            report = registry.plugin_discovery_report()
            self.assertEqual(report["signing_mode"], "strict")
            self.assertGreaterEqual(int(report["summary"].get("blocked", 0)), 1)

    def test_warn_mode_allows_unsigned_plugin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-plugin-signing-") as tmp:
            plugins_dir = Path(tmp)
            self._write_plugin(
                plugins_dir=plugins_dir,
                plugin_dir_name="unsigned_warn",
                manifest=self._manifest("warn_tool"),
            )

            registry = ToolRegistry(plugin_signing_key="secret", plugin_signing_mode="warn")
            registry.discover_plugins(plugins_dir)

            self.assertIn("warn_tool", registry.names())
            report = registry.plugin_discovery_report()
            self.assertGreaterEqual(int(report["summary"].get("loaded", 0)), 1)
            events = report.get("events", [])
            self.assertTrue(any(str(item.get("signature_state", "")).startswith("warn_") for item in events))

    def test_strict_mode_accepts_valid_signature(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-plugin-signing-") as tmp:
            plugins_dir = Path(tmp)
            secret = "super-secret"
            manifest = self._manifest("signed_tool")
            signed_manifest = self._sign_manifest(manifest=manifest, key=secret)
            self._write_plugin(
                plugins_dir=plugins_dir,
                plugin_dir_name="signed",
                manifest=signed_manifest,
            )

            registry = ToolRegistry(plugin_signing_key=secret, plugin_signing_mode="strict")
            registry.discover_plugins(plugins_dir)

            self.assertIn("signed_tool", registry.names())
            report = registry.plugin_discovery_report()
            self.assertGreaterEqual(int(report["summary"].get("loaded", 0)), 1)
            self.assertTrue(any(item.get("signature_state") == "verified" for item in report.get("events", [])))

    def test_missing_compat_blocks_plugin_before_signature(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-plugin-signing-") as tmp:
            plugins_dir = Path(tmp)
            manifest = self._manifest("missing_compat_tool")
            manifest.pop("compat", None)
            self._write_plugin(
                plugins_dir=plugins_dir,
                plugin_dir_name="missing_compat",
                manifest=manifest,
            )

            registry = ToolRegistry(plugin_signing_mode="off")
            registry.discover_plugins(plugins_dir)

            self.assertNotIn("missing_compat_tool", registry.names())
            report = registry.plugin_discovery_report()
            self.assertGreaterEqual(int(report["summary"].get("blocked", 0)), 1)
            self.assertGreaterEqual(int(report["compat_summary"].get("incompatible", 0)), 1)
            events = report.get("events", [])
            self.assertTrue(any(str(item.get("reason", "")).startswith("compat_incompatible:") for item in events))
            self.assertTrue(any(item.get("signature_state") == "not_checked" for item in events))

    def test_runtime_mode_mismatch_blocks_plugin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-plugin-signing-") as tmp:
            plugins_dir = Path(tmp)
            manifest = self._manifest("legacy_only_tool", runtime_modes=["legacy"])
            self._write_plugin(
                plugins_dir=plugins_dir,
                plugin_dir_name="legacy_only",
                manifest=manifest,
            )

            registry = ToolRegistry(
                plugin_signing_mode="off",
                plugin_runtime_mode="sandboxed",
            )
            registry.discover_plugins(plugins_dir)

            self.assertNotIn("legacy_only_tool", registry.names())
            report = registry.plugin_discovery_report()
            self.assertEqual(report["compat_contract"]["manifest_version"], PLUGIN_COMPAT_MANIFEST_VERSION)
            self.assertEqual(report["compat_contract"]["tool_registry_api"], PLUGIN_REGISTRY_API_VERSION)
            events = report.get("events", [])
            self.assertTrue(any("runtime compatibility mismatch" in str(item.get("compat_reason", "")) for item in events))

    def test_unknown_capability_blocks_plugin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-plugin-signing-") as tmp:
            plugins_dir = Path(tmp)
            manifest = self._manifest("unknown_cap_tool", capabilities=["filesystem_read", "root"])
            self._write_plugin(
                plugins_dir=plugins_dir,
                plugin_dir_name="unknown_capability",
                manifest=manifest,
            )

            registry = ToolRegistry(plugin_signing_mode="off")
            registry.discover_plugins(plugins_dir)

            self.assertNotIn("unknown_cap_tool", registry.names())
            report = registry.plugin_discovery_report()
            self.assertGreaterEqual(int(report["summary"].get("blocked", 0)), 1)
            self.assertGreaterEqual(int(report["capability_summary"].get("incompatible", 0)), 1)
            events = report.get("events", [])
            self.assertTrue(any(str(item.get("reason", "")).startswith("capability_incompatible:") for item in events))

    @staticmethod
    def _write_plugin(
        *,
        plugins_dir: Path,
        plugin_dir_name: str,
        manifest: dict,
    ) -> None:
        target = plugins_dir / plugin_dir_name
        target.mkdir(parents=True, exist_ok=True)
        (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        (target / "tool.py").write_text(PLUGIN_TOOL_CODE + "\n", encoding="utf-8")

    @staticmethod
    def _manifest(
        name: str,
        runtime_modes: list[str] | None = None,
        capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        modes = list(runtime_modes or ["sandboxed", "legacy"])
        caps = list(capabilities or ["filesystem_read"])
        return {
            "name": name,
            "version": "1.0.0",
            "compat": {
                "manifest_version": PLUGIN_COMPAT_MANIFEST_VERSION,
                "tool_registry_api": PLUGIN_REGISTRY_API_VERSION,
                "runtime_modes": modes,
            },
            "capabilities": caps,
            "tool": {
                "name": name,
                "description": "plugin test tool",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
                "risk_level": "low",
                "approval_mode": "none",
                "entrypoint": "execute",
            },
        }

    @staticmethod
    def _sign_manifest(*, manifest: dict, key: str) -> dict:
        payload = dict(manifest)
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        signature = hmac.new(key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        payload["signature"] = signature
        return payload


if __name__ == "__main__":
    unittest.main()
