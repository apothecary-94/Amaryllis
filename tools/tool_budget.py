from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
import time


@dataclass(frozen=True)
class ToolBudgetLimits:
    window_sec: float
    max_calls_per_tool: int
    max_total_calls: int
    max_high_risk_calls: int


@dataclass(frozen=True)
class ToolBudgetStatus:
    scope: str
    window_sec: float
    total_calls: int
    high_risk_calls: int
    per_tool_calls: int
    max_total_calls: int
    max_high_risk_calls: int
    max_calls_per_tool: int


@dataclass(frozen=True)
class _ToolCallRecord:
    ts: float
    tool_name: str
    risk_level: str


class ToolBudgetExceededError(RuntimeError):
    pass


class ToolBudgetGuard:
    def __init__(
        self,
        *,
        window_sec: float = 60.0,
        max_calls_per_tool: int = 12,
        max_total_calls: int = 40,
        max_high_risk_calls: int = 4,
    ) -> None:
        self.limits = ToolBudgetLimits(
            window_sec=max(1.0, float(window_sec)),
            max_calls_per_tool=max(1, int(max_calls_per_tool)),
            max_total_calls=max(1, int(max_total_calls)),
            max_high_risk_calls=max(1, int(max_high_risk_calls)),
        )
        self._records_by_scope: dict[str, deque[_ToolCallRecord]] = {}
        self._lock = Lock()

    def check_and_record(
        self,
        *,
        tool_name: str,
        risk_level: str,
        request_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> ToolBudgetStatus:
        now = time.monotonic()
        scope = self._scope_key(
            request_id=request_id,
            user_id=user_id,
            session_id=session_id,
        )
        normalized_tool = str(tool_name or "").strip()
        normalized_risk = str(risk_level or "low").strip().lower()
        is_high_risk = normalized_risk in {"high", "critical"}

        with self._lock:
            records = self._records_by_scope.setdefault(scope, deque())
            self._prune(records=records, now=now)

            total_calls = len(records)
            per_tool_calls = sum(1 for item in records if item.tool_name == normalized_tool)
            high_risk_calls = sum(
                1
                for item in records
                if item.risk_level in {"high", "critical"}
            )

            if total_calls >= self.limits.max_total_calls:
                raise ToolBudgetExceededError(
                    (
                        f"Tool budget limit reached for scope '{scope}': "
                        f"total_calls={total_calls}/{self.limits.max_total_calls} "
                        f"in {self.limits.window_sec:.0f}s window."
                    )
                )

            if per_tool_calls >= self.limits.max_calls_per_tool:
                raise ToolBudgetExceededError(
                    (
                        f"Tool budget limit reached for '{normalized_tool}' in scope '{scope}': "
                        f"per_tool_calls={per_tool_calls}/{self.limits.max_calls_per_tool} "
                        f"in {self.limits.window_sec:.0f}s window."
                    )
                )

            if is_high_risk and high_risk_calls >= self.limits.max_high_risk_calls:
                raise ToolBudgetExceededError(
                    (
                        f"High-risk tool budget limit reached for scope '{scope}': "
                        f"high_risk_calls={high_risk_calls}/{self.limits.max_high_risk_calls} "
                        f"in {self.limits.window_sec:.0f}s window."
                    )
                )

            records.append(
                _ToolCallRecord(
                    ts=now,
                    tool_name=normalized_tool,
                    risk_level=normalized_risk,
                )
            )

            return ToolBudgetStatus(
                scope=scope,
                window_sec=self.limits.window_sec,
                total_calls=total_calls + 1,
                high_risk_calls=high_risk_calls + (1 if is_high_risk else 0),
                per_tool_calls=per_tool_calls + 1,
                max_total_calls=self.limits.max_total_calls,
                max_high_risk_calls=self.limits.max_high_risk_calls,
                max_calls_per_tool=self.limits.max_calls_per_tool,
            )

    def _scope_key(
        self,
        *,
        request_id: str | None,
        user_id: str | None,
        session_id: str | None,
    ) -> str:
        if session_id and session_id.strip():
            return f"session:{session_id.strip()}"
        if user_id and user_id.strip():
            return f"user:{user_id.strip()}"
        if request_id and request_id.strip():
            return f"request:{request_id.strip()}"
        return "global"

    def _prune(self, *, records: deque[_ToolCallRecord], now: float) -> None:
        cutoff = now - self.limits.window_sec
        while records and records[0].ts < cutoff:
            records.popleft()
