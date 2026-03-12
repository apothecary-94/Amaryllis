from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.tool_registry import ToolDefinition


@dataclass(frozen=True)
class ToolDecision:
    allow: bool
    requires_approval: bool
    reason: str | None = None


class ToolIsolationPolicy:
    def __init__(
        self,
        blocked_tools: list[str] | None = None,
        profile: str = "balanced",
        allowed_high_risk_tools: list[str] | None = None,
        python_exec_max_timeout_sec: int = 10,
        python_exec_max_code_chars: int = 4000,
        filesystem_allow_write: bool = True,
    ) -> None:
        self.blocked_tools = {item.strip() for item in (blocked_tools or []) if item.strip()}
        normalized_profile = str(profile or "balanced").strip().lower()
        if normalized_profile not in {"balanced", "strict"}:
            normalized_profile = "balanced"
        self.profile = normalized_profile
        self.allowed_high_risk_tools = {
            item.strip()
            for item in (allowed_high_risk_tools or [])
            if item and item.strip()
        }
        self.python_exec_max_timeout_sec = max(1, int(python_exec_max_timeout_sec))
        self.python_exec_max_code_chars = max(100, int(python_exec_max_code_chars))
        self.filesystem_allow_write = bool(filesystem_allow_write)

    def evaluate(self, tool: ToolDefinition, arguments: dict[str, Any]) -> ToolDecision:
        if tool.name in self.blocked_tools:
            return ToolDecision(
                allow=False,
                requires_approval=False,
                reason="Tool is blocked by policy.",
            )

        if self.profile == "strict" and tool.risk_level == "high" and tool.name not in self.allowed_high_risk_tools:
            return ToolDecision(
                allow=False,
                requires_approval=False,
                reason=(
                    f"Tool '{tool.name}' is high-risk and blocked in strict isolation profile. "
                    "Allow explicitly via policy config."
                ),
            )

        tool_name = str(tool.name).strip().lower()
        if tool_name == "python_exec":
            code = str(arguments.get("code", ""))
            if len(code) > self.python_exec_max_code_chars:
                return ToolDecision(
                    allow=False,
                    requires_approval=False,
                    reason=(
                        f"python_exec code size exceeds limit "
                        f"({len(code)} > {self.python_exec_max_code_chars})."
                    ),
                )
            try:
                timeout = int(arguments.get("timeout", 8))
            except Exception:
                timeout = 8
            if timeout > self.python_exec_max_timeout_sec:
                return ToolDecision(
                    allow=False,
                    requires_approval=False,
                    reason=(
                        f"python_exec timeout exceeds limit "
                        f"({timeout}s > {self.python_exec_max_timeout_sec}s)."
                    ),
                )

        if tool_name == "filesystem":
            action = str(arguments.get("action", "")).strip().lower()
            if action == "write" and not self.filesystem_allow_write:
                return ToolDecision(
                    allow=False,
                    requires_approval=False,
                    reason="filesystem write is disabled by isolation policy.",
                )

        requires_approval = False
        if tool.approval_mode == "required":
            requires_approval = True
        elif tool.approval_mode == "conditional" and tool.approval_predicate is not None:
            try:
                requires_approval = bool(tool.approval_predicate(arguments))
            except Exception:
                requires_approval = True

        if self.profile == "strict" and tool.risk_level in {"high", "critical"}:
            requires_approval = True
        if self.profile == "strict" and tool_name == "filesystem":
            action = str(arguments.get("action", "")).strip().lower()
            if action == "write":
                requires_approval = True

        return ToolDecision(
            allow=True,
            requires_approval=requires_approval,
            reason=None,
        )
