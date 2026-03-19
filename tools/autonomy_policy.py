from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VALID_AUTONOMY_LEVELS: tuple[str, ...] = ("l0", "l1", "l2", "l3", "l4", "l5")
_VALID_RISKS = {"low", "medium", "high", "critical"}


def normalize_autonomy_level(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in VALID_AUTONOMY_LEVELS:
        return "l3"
    return normalized


def normalize_risk_level(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _VALID_RISKS:
        return "medium"
    return normalized


@dataclass(frozen=True)
class AutonomyDecision:
    allow: bool
    requires_approval: bool
    reason: str | None = None
    approval_scope: str | None = None
    approval_ttl_sec: int | None = None


class AutonomyPolicy:
    def __init__(self, level: str = "l3") -> None:
        self.level = normalize_autonomy_level(level)

    def evaluate(self, *, tool_name: str, risk_level: str) -> AutonomyDecision:
        normalized_risk = normalize_risk_level(risk_level)
        level = self.level
        label = level.upper()

        if level == "l0":
            return AutonomyDecision(
                allow=False,
                requires_approval=False,
                reason=f"Autonomy level {label} blocks all tool execution.",
            )

        if level == "l1":
            if normalized_risk != "low":
                return AutonomyDecision(
                    allow=False,
                    requires_approval=False,
                    reason=(
                        f"Autonomy level {label} blocks non-low-risk tool '{tool_name}' "
                        f"(risk={normalized_risk})."
                    ),
                )
            return AutonomyDecision(
                allow=True,
                requires_approval=True,
                reason=f"Autonomy level {label} requires approval for low-risk tool execution.",
                approval_scope="request",
                approval_ttl_sec=180,
            )

        if level == "l2":
            if normalized_risk in {"high", "critical"}:
                return AutonomyDecision(
                    allow=False,
                    requires_approval=False,
                    reason=(
                        f"Autonomy level {label} blocks high-risk tool '{tool_name}' "
                        f"(risk={normalized_risk})."
                    ),
                )
            if normalized_risk == "medium":
                return AutonomyDecision(
                    allow=True,
                    requires_approval=True,
                    reason=f"Autonomy level {label} requires approval for medium-risk tool execution.",
                    approval_scope="request",
                    approval_ttl_sec=300,
                )
            return AutonomyDecision(allow=True, requires_approval=False)

        if level == "l3":
            if normalized_risk == "critical":
                return AutonomyDecision(
                    allow=False,
                    requires_approval=False,
                    reason=(
                        f"Autonomy level {label} blocks critical-risk tool '{tool_name}' "
                        f"(risk={normalized_risk})."
                    ),
                )
            if normalized_risk == "high":
                return AutonomyDecision(
                    allow=True,
                    requires_approval=True,
                    reason=f"Autonomy level {label} requires approval for high-risk tool execution.",
                    approval_scope="request",
                    approval_ttl_sec=300,
                )
            return AutonomyDecision(allow=True, requires_approval=False)

        if level == "l4":
            if normalized_risk == "critical":
                return AutonomyDecision(
                    allow=True,
                    requires_approval=True,
                    reason=f"Autonomy level {label} requires approval for critical-risk tool execution.",
                    approval_scope="session",
                    approval_ttl_sec=900,
                )
            if normalized_risk == "high":
                return AutonomyDecision(
                    allow=True,
                    requires_approval=True,
                    reason=f"Autonomy level {label} requires approval for high-risk tool execution.",
                    approval_scope="session",
                    approval_ttl_sec=600,
                )
            return AutonomyDecision(allow=True, requires_approval=False)

        # L5: bounded full autonomy by tool policy controls.
        return AutonomyDecision(allow=True, requires_approval=False)

    def describe(self) -> dict[str, Any]:
        rules = {
            "l0": "all tools blocked",
            "l1": "only low-risk tools with per-request approval",
            "l2": "low-risk auto; medium with approval; high/critical blocked",
            "l3": "low/medium auto; high with approval; critical blocked",
            "l4": "low/medium auto; high/critical with approval",
            "l5": "autonomy policy allows all; isolation/approval controls still apply",
        }
        return {
            "level": self.level,
            "rules": rules,
        }
