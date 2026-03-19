from __future__ import annotations

import unittest

from agents.agent_run_manager import RunBudgetExceededError, RunLeaseLostError
from agents.run_policy import classify_failure, resolve_retry_decision, retry_delay_seconds
from models.provider_errors import ProviderErrorInfo, ProviderOperationError
from tasks.task_executor import TaskGuardrailError, TaskTimeoutError


class RunPolicyTests(unittest.TestCase):
    def test_classify_provider_error_uses_provider_class_and_retryability(self) -> None:
        info = ProviderErrorInfo(
            provider="openai",
            operation="chat",
            error_class="rate_limit",  # type: ignore[arg-type]
            message="429",
            raw_message="429",
            retryable=True,
            status_code=429,
        )
        error = ProviderOperationError(info)

        decision = classify_failure(
            error,
            run_budget_error_type=RunBudgetExceededError,
            run_lease_lost_error_type=RunLeaseLostError,
            task_timeout_error_type=TaskTimeoutError,
            task_guardrail_error_type=TaskGuardrailError,
            provider_operation_error_type=ProviderOperationError,
            provider_error_classifier=lambda **_: info,
        )

        self.assertEqual(decision.failure_class, "rate_limit")
        self.assertEqual(decision.stop_reason, "provider_rate_limit")
        self.assertTrue(decision.retryable)

    def test_classify_guardrail_budget_maps_to_budget_exceeded(self) -> None:
        decision = classify_failure(
            TaskGuardrailError("budget exceeded"),
            run_budget_error_type=RunBudgetExceededError,
            run_lease_lost_error_type=RunLeaseLostError,
            task_timeout_error_type=TaskTimeoutError,
            task_guardrail_error_type=TaskGuardrailError,
            provider_operation_error_type=ProviderOperationError,
            provider_error_classifier=lambda **_: None,
        )
        self.assertEqual(decision.failure_class, "budget_exceeded")
        self.assertEqual(decision.stop_reason, "budget_exceeded")
        self.assertFalse(decision.retryable)

    def test_resolve_retry_decision_schedules_retry_when_allowed(self) -> None:
        decision = resolve_retry_decision(
            attempt=1,
            max_attempts=3,
            retryable=True,
            canceled=False,
            stop_reason="provider_rate_limit",
            failure_class="rate_limit",
            cancel_stop_reason="canceled_by_user",
        )
        self.assertTrue(decision.schedule_retry)
        self.assertIsNone(decision.final_status)

    def test_resolve_retry_decision_marks_max_attempts_exhausted(self) -> None:
        decision = resolve_retry_decision(
            attempt=3,
            max_attempts=3,
            retryable=True,
            canceled=False,
            stop_reason="provider_rate_limit",
            failure_class="rate_limit",
            cancel_stop_reason="canceled_by_user",
        )
        self.assertFalse(decision.schedule_retry)
        self.assertEqual(decision.final_status, "failed")
        self.assertEqual(decision.final_failure_class, "rate_limit")
        self.assertEqual(decision.final_stop_reason, "max_attempts_exhausted")

    def test_retry_delay_seconds_is_stable_without_jitter(self) -> None:
        self.assertEqual(
            retry_delay_seconds(
                attempt=1,
                retry_backoff_sec=0.3,
                retry_max_backoff_sec=2.0,
                retry_jitter_sec=0.0,
            ),
            0.3,
        )
        self.assertEqual(
            retry_delay_seconds(
                attempt=4,
                retry_backoff_sec=0.3,
                retry_max_backoff_sec=2.0,
                retry_jitter_sec=0.0,
            ),
            2.0,
        )


if __name__ == "__main__":
    unittest.main()
