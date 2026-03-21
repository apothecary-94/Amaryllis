from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PLUGIN_CAPABILITY_MATRIX: dict[str, dict[str, Any]] = {
    "filesystem_read": {
        "default_allowed": True,
        "requires_approval": False,
        "notes": "Read access is limited to sandbox allowed roots.",
    },
    "filesystem_write": {
        "default_allowed": True,
        "requires_approval": True,
        "notes": "Write access is limited to sandbox allowed roots and explicit policy gates.",
    },
    "network": {
        "default_allowed": False,
        "requires_approval": True,
        "notes": "Network access requires explicit policy allowlist and sandbox opt-in.",
    },
    "process": {
        "default_allowed": False,
        "requires_approval": False,
        "notes": "Subprocess execution is blocked by sandbox worker.",
    },
}

_BLOCKED_CAPABILITIES: set[str] = {"process"}


@dataclass(frozen=True)
class PluginCapabilityValidation:
    ok: bool
    reason: str
    capabilities: tuple[str, ...]


def plugin_capability_policy_snapshot() -> dict[str, Any]:
    return {
        "capabilities": {
            name: {
                "default_allowed": bool(spec.get("default_allowed", False)),
                "requires_approval": bool(spec.get("requires_approval", False)),
                "notes": str(spec.get("notes") or ""),
            }
            for name, spec in sorted(PLUGIN_CAPABILITY_MATRIX.items())
        },
        "blocked_capabilities": sorted(_BLOCKED_CAPABILITIES),
        "default_allowed_capabilities": default_allowed_plugin_capabilities(),
    }


def supported_plugin_capabilities() -> set[str]:
    return set(PLUGIN_CAPABILITY_MATRIX.keys())


def default_allowed_plugin_capabilities() -> list[str]:
    return sorted(
        name
        for name, spec in PLUGIN_CAPABILITY_MATRIX.items()
        if bool(spec.get("default_allowed", False))
    )


def plugin_capabilities_requiring_approval() -> set[str]:
    return {
        name
        for name, spec in PLUGIN_CAPABILITY_MATRIX.items()
        if bool(spec.get("requires_approval", False))
    }


def validate_plugin_manifest_capabilities(*, manifest: dict[str, Any]) -> PluginCapabilityValidation:
    raw = manifest.get("capabilities")
    if not isinstance(raw, list) or not raw:
        return PluginCapabilityValidation(
            ok=False,
            reason="manifest field 'capabilities' must be a non-empty array",
            capabilities=tuple(),
        )

    normalized = sorted({str(item).strip().lower() for item in raw if str(item).strip()})
    if not normalized:
        return PluginCapabilityValidation(
            ok=False,
            reason="manifest field 'capabilities' must contain at least one non-empty value",
            capabilities=tuple(),
        )

    supported = supported_plugin_capabilities()
    invalid = [item for item in normalized if item not in supported]
    if invalid:
        return PluginCapabilityValidation(
            ok=False,
            reason=f"manifest field 'capabilities' contains unsupported values: {', '.join(invalid)}",
            capabilities=tuple(),
        )

    blocked = sorted(item for item in normalized if item in _BLOCKED_CAPABILITIES)
    if blocked:
        return PluginCapabilityValidation(
            ok=False,
            reason=f"manifest field 'capabilities' includes blocked values: {', '.join(blocked)}",
            capabilities=tuple(normalized),
        )

    if "filesystem_write" in normalized and "filesystem_read" not in normalized:
        return PluginCapabilityValidation(
            ok=False,
            reason="manifest capability 'filesystem_write' requires 'filesystem_read'",
            capabilities=tuple(normalized),
        )

    return PluginCapabilityValidation(
        ok=True,
        reason="capability_contract_ok",
        capabilities=tuple(normalized),
    )
