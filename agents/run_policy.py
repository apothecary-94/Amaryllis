from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable

RUN_RETRYABLE_FAILURE_CLASSES: set[str] = {
    "timeout",
    "rate_limit",
    "network",
    "server",
    "unavailable",
    "circuit_open",
}
KILL_SWITCH_STOP_REASON = "kill_switch_triggered"


@dataclass(frozen=True)
class FailureDecision:
    failure_class: str
    stop_reason: str
    retryable: bool


@dataclass(frozen=True)
class RetryDecision:
    schedule_retry: bool
    final_status: str | None = None
    final_failure_class: str | None = None
    final_stop_reason: str | None = None


def classify_failure(
    exc: Exception,
    *,
    run_budget_error_type: type[BaseException],
    run_lease_lost_error_type: type[BaseException],
    task_timeout_error_type: type[BaseException],
    task_guardrail_error_type: type[BaseException],
    provider_operation_error_type: type[BaseException],
    provider_error_classifier: Callable[..., Any],
    retryable_failure_classes: set[str] | None = None,
) -> FailureDecision:
    retryable_classes = retryable_failure_classes or RUN_RETRYABLE_FAILURE_CLASSES

    if isinstance(exc, run_budget_error_type):
        return FailureDecision(
            failure_class="budget_exceeded",
            stop_reason="budget_exceeded",
            retryable=False,
        )
    if isinstance(exc, run_lease_lost_error_type):
        return FailureDecision(
            failure_class="lease_lost",
            stop_reason="lease_lost",
            retryable=True,
        )
    if isinstance(exc, task_timeout_error_type):
        return FailureDecision(
            failure_class="timeout",
            stop_reason="timeout",
            retryable=True,
        )
    if isinstance(exc, task_guardrail_error_type):
        message = str(exc).lower()
        if "budget" in message:
            return FailureDecision(
                failure_class="budget_exceeded",
                stop_reason="budget_exceeded",
                retryable=False,
            )
        return FailureDecision(
            failure_class="guardrail",
            stop_reason="guardrail_rejected",
            retryable=False,
        )
    if isinstance(exc, provider_operation_error_type):
        info = getattr(exc, "info", None)
        error_class = str(getattr(info, "error_class", "unknown"))
        return FailureDecision(
            failure_class=error_class,
            stop_reason=f"provider_{error_class}",
            retryable=error_class in retryable_classes,
        )
    if isinstance(exc, (ValueError, TypeError, AssertionError)):
        return FailureDecision(
            failure_class="invalid_request",
            stop_reason="invalid_request",
            retryable=False,
        )

    provider_info = provider_error_classifier(
        provider="unknown",
        operation="agent_run",
        error=exc,
    )
    provider_class = str(getattr(provider_info, "error_class", "unknown"))
    if provider_class != "unknown":
        return FailureDecision(
            failure_class=provider_class,
            stop_reason=f"provider_{provider_class}",
            retryable=provider_class in retryable_classes,
        )

    return FailureDecision(
        failure_class="unknown",
        stop_reason="unknown_error",
        retryable=False,
    )


def resolve_retry_decision(
    *,
    attempt: int,
    max_attempts: int,
    retryable: bool,
    canceled: bool,
    stop_reason: str,
    failure_class: str,
    cancel_stop_reason: str,
) -> RetryDecision:
    schedule_retry = bool(attempt < max_attempts and not canceled and retryable)
    if schedule_retry:
        return RetryDecision(schedule_retry=True)

    final_status = "canceled" if canceled else "failed"
    final_failure_class = "canceled" if canceled else str(failure_class)
    final_stop_reason = str(cancel_stop_reason) if canceled else str(stop_reason)
    if not canceled and retryable and attempt >= max_attempts:
        final_stop_reason = "max_attempts_exhausted"
    return RetryDecision(
        schedule_retry=False,
        final_status=final_status,
        final_failure_class=final_failure_class,
        final_stop_reason=final_stop_reason,
    )


def retry_delay_seconds(
    *,
    attempt: int,
    retry_backoff_sec: float,
    retry_max_backoff_sec: float,
    retry_jitter_sec: float,
) -> float:
    if retry_backoff_sec <= 0:
        return 0.0
    exponential = retry_backoff_sec * (2 ** max(0, int(attempt) - 1))
    bounded = min(exponential, retry_max_backoff_sec) if retry_max_backoff_sec > 0 else exponential
    jitter = random.uniform(0.0, retry_jitter_sec) if retry_jitter_sec > 0 else 0.0
    return round(max(0.0, bounded + jitter), 3)

