from __future__ import annotations

from copy import deepcopy
from typing import Any

_SLO_KEYS: tuple[str, ...] = (
    "warning_failures",
    "critical_failures",
    "disable_failures",
    "backoff_base_sec",
    "backoff_max_sec",
    "circuit_failure_threshold",
    "circuit_open_sec",
)

_MISSION_POLICY_PROFILES: dict[str, dict[str, Any]] = {
    "balanced": {
        "id": "balanced",
        "name": "Balanced",
        "description": "Default tradeoff between fast retries and stability.",
        "slo": {
            "warning_failures": 2,
            "critical_failures": 4,
            "disable_failures": 6,
            "backoff_base_sec": 5.0,
            "backoff_max_sec": 300.0,
            "circuit_failure_threshold": 4,
            "circuit_open_sec": 120.0,
        },
    },
    "strict": {
        "id": "strict",
        "name": "Strict Reliability",
        "description": "Faster escalation and stronger containment after repeated failures.",
        "slo": {
            "warning_failures": 1,
            "critical_failures": 2,
            "disable_failures": 3,
            "backoff_base_sec": 10.0,
            "backoff_max_sec": 600.0,
            "circuit_failure_threshold": 2,
            "circuit_open_sec": 300.0,
        },
    },
    "watchdog": {
        "id": "watchdog",
        "name": "Watchdog",
        "description": "Aggressive retry for monitoring loops with quick circuit recovery.",
        "slo": {
            "warning_failures": 1,
            "critical_failures": 2,
            "disable_failures": 4,
            "backoff_base_sec": 3.0,
            "backoff_max_sec": 90.0,
            "circuit_failure_threshold": 3,
            "circuit_open_sec": 90.0,
        },
    },
    "release": {
        "id": "release",
        "name": "Release Gate",
        "description": "Conservative release posture with early warning and hard guardrails.",
        "slo": {
            "warning_failures": 1,
            "critical_failures": 2,
            "disable_failures": 3,
            "backoff_base_sec": 15.0,
            "backoff_max_sec": 900.0,
            "circuit_failure_threshold": 2,
            "circuit_open_sec": 600.0,
        },
    },
}


def list_mission_policy_profiles() -> list[dict[str, Any]]:
    return [deepcopy(_MISSION_POLICY_PROFILES[key]) for key in sorted(_MISSION_POLICY_PROFILES)]


def resolve_mission_policy_overlay(
    *,
    policy: dict[str, Any] | None,
    profile: str | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = _normalize_policy(
        defaults if isinstance(defaults, dict) else _MISSION_POLICY_PROFILES["balanced"],
        default_profile="balanced",
    )
    explicit_profile = _normalize_profile(profile)
    policy_profile = _normalize_profile(policy.get("profile")) if isinstance(policy, dict) else None
    selected_profile = explicit_profile
    if selected_profile is None:
        selected_profile = policy_profile
    if selected_profile is None:
        selected_profile = str(base.get("profile") or "balanced")

    if selected_profile in _MISSION_POLICY_PROFILES:
        profile_slo = deepcopy(_MISSION_POLICY_PROFILES[selected_profile]["slo"])
        base["slo"] = _normalize_slo(profile_slo, fallback=base["slo"])
    elif explicit_profile is not None:
        raise ValueError(f"unsupported mission policy profile: {selected_profile}")

    if isinstance(policy, dict):
        if isinstance(policy.get("slo"), dict):
            merged = dict(base["slo"])
            for key in _SLO_KEYS:
                if key in policy["slo"]:
                    merged[key] = policy["slo"][key]
            base["slo"] = _normalize_slo(merged, fallback=base["slo"])
        else:
            flat_overrides = {
                key: policy[key]
                for key in _SLO_KEYS
                if key in policy
            }
            if flat_overrides:
                merged = dict(base["slo"])
                merged.update(flat_overrides)
                base["slo"] = _normalize_slo(merged, fallback=base["slo"])

    base["profile"] = selected_profile
    return base


def _normalize_profile(value: Any) -> str | None:
    token = str(value or "").strip().lower()
    if not token:
        return None
    return token.replace("-", "_")


def _normalize_policy(raw: dict[str, Any], *, default_profile: str) -> dict[str, Any]:
    profile = _normalize_profile(raw.get("profile")) or default_profile
    slo_raw = raw.get("slo")
    if not isinstance(slo_raw, dict):
        if profile in _MISSION_POLICY_PROFILES:
            slo_raw = deepcopy(_MISSION_POLICY_PROFILES[profile]["slo"])
        else:
            slo_raw = deepcopy(_MISSION_POLICY_PROFILES["balanced"]["slo"])
    normalized_slo = _normalize_slo(slo_raw, fallback=deepcopy(_MISSION_POLICY_PROFILES["balanced"]["slo"]))
    return {
        "profile": profile,
        "slo": normalized_slo,
    }


def _normalize_slo(raw: dict[str, Any], *, fallback: dict[str, Any]) -> dict[str, Any]:
    def _as_int(key: str, minimum: int, default: int) -> int:
        value = raw.get(key, default)
        try:
            parsed = int(value)
        except Exception:
            parsed = int(default)
        return max(minimum, parsed)

    def _as_float(key: str, minimum: float, default: float) -> float:
        value = raw.get(key, default)
        try:
            parsed = float(value)
        except Exception:
            parsed = float(default)
        return max(minimum, parsed)

    warning = _as_int("warning_failures", 1, int(fallback.get("warning_failures", 2)))
    critical = _as_int("critical_failures", warning, int(fallback.get("critical_failures", 4)))
    disable = _as_int("disable_failures", critical + 1, int(fallback.get("disable_failures", 6)))
    backoff_base = _as_float("backoff_base_sec", 1.0, float(fallback.get("backoff_base_sec", 5.0)))
    backoff_max = _as_float("backoff_max_sec", backoff_base, float(fallback.get("backoff_max_sec", 300.0)))
    circuit_failure_threshold = _as_int(
        "circuit_failure_threshold",
        1,
        int(fallback.get("circuit_failure_threshold", 4)),
    )
    circuit_open_sec = _as_float("circuit_open_sec", 1.0, float(fallback.get("circuit_open_sec", 120.0)))

    return {
        "warning_failures": warning,
        "critical_failures": critical,
        "disable_failures": disable,
        "backoff_base_sec": backoff_base,
        "backoff_max_sec": backoff_max,
        "circuit_failure_threshold": circuit_failure_threshold,
        "circuit_open_sec": circuit_open_sec,
    }
