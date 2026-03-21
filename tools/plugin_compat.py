from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PLUGIN_COMPAT_MANIFEST_VERSION = "v1"
PLUGIN_REGISTRY_API_VERSION = "v1"
_ALLOWED_RUNTIME_MODES: set[str] = {"sandboxed", "legacy"}


@dataclass(frozen=True)
class PluginCompatValidation:
    ok: bool
    reason: str


def plugin_compat_contract_snapshot() -> dict[str, Any]:
    return {
        "manifest_version": PLUGIN_COMPAT_MANIFEST_VERSION,
        "tool_registry_api": PLUGIN_REGISTRY_API_VERSION,
        "allowed_runtime_modes": sorted(_ALLOWED_RUNTIME_MODES),
    }


def validate_plugin_manifest_compat(*, manifest: dict[str, Any], runtime_mode: str) -> PluginCompatValidation:
    name = str(manifest.get("name") or "").strip()
    if not name:
        return PluginCompatValidation(ok=False, reason="manifest field 'name' must be non-empty")

    version = str(manifest.get("version") or "").strip()
    if not version:
        return PluginCompatValidation(ok=False, reason="manifest field 'version' must be non-empty")

    compat = manifest.get("compat")
    if not isinstance(compat, dict):
        return PluginCompatValidation(
            ok=False,
            reason=(
                "manifest field 'compat' must be an object "
                f"(expected manifest_version={PLUGIN_COMPAT_MANIFEST_VERSION})"
            ),
        )

    manifest_version = str(compat.get("manifest_version") or "").strip()
    if manifest_version != PLUGIN_COMPAT_MANIFEST_VERSION:
        return PluginCompatValidation(
            ok=False,
            reason=(
                "unsupported compat.manifest_version "
                f"'{manifest_version or '<empty>'}' (expected {PLUGIN_COMPAT_MANIFEST_VERSION})"
            ),
        )

    registry_api = str(compat.get("tool_registry_api") or "").strip()
    if registry_api != PLUGIN_REGISTRY_API_VERSION:
        return PluginCompatValidation(
            ok=False,
            reason=(
                "unsupported compat.tool_registry_api "
                f"'{registry_api or '<empty>'}' (expected {PLUGIN_REGISTRY_API_VERSION})"
            ),
        )

    runtime_modes = compat.get("runtime_modes")
    if not isinstance(runtime_modes, list) or not runtime_modes:
        return PluginCompatValidation(
            ok=False,
            reason="compat.runtime_modes must be a non-empty array",
        )

    normalized_modes = {
        str(item).strip().lower()
        for item in runtime_modes
        if str(item).strip()
    }
    if not normalized_modes:
        return PluginCompatValidation(
            ok=False,
            reason="compat.runtime_modes must contain at least one non-empty mode",
        )

    invalid_modes = sorted(mode for mode in normalized_modes if mode not in _ALLOWED_RUNTIME_MODES)
    if invalid_modes:
        return PluginCompatValidation(
            ok=False,
            reason=f"compat.runtime_modes contains unsupported values: {', '.join(invalid_modes)}",
        )

    normalized_runtime_mode = str(runtime_mode or "").strip().lower() or "sandboxed"
    if normalized_runtime_mode not in normalized_modes:
        allowed = ", ".join(sorted(normalized_modes))
        return PluginCompatValidation(
            ok=False,
            reason=(
                "plugin runtime compatibility mismatch: "
                f"registry mode='{normalized_runtime_mode}' not in compat.runtime_modes=[{allowed}]"
            ),
        )

    return PluginCompatValidation(ok=True, reason="compatibility_contract_ok")
