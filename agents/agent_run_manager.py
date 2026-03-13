from __future__ import annotations

import logging
import random
from queue import Empty, Queue
from threading import Event, Thread
from datetime import datetime, timezone
import time
from typing import Any, Protocol
from uuid import uuid4

from agents.agent import Agent
from models.provider_errors import ProviderOperationError, classify_provider_error
from storage.database import Database
from tasks.task_executor import TaskExecutor, TaskGuardrailError, TaskTimeoutError


class TelemetrySink(Protocol):
    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        ...


class RunBudgetExceededError(TaskGuardrailError):
    pass


RUN_RETRYABLE_FAILURE_CLASSES: set[str] = {
    "timeout",
    "rate_limit",
    "network",
    "server",
    "unavailable",
    "circuit_open",
}


class AgentRunManager:
    def __init__(
        self,
        database: Database,
        task_executor: TaskExecutor,
        worker_count: int = 2,
        default_max_attempts: int = 2,
        attempt_timeout_sec: float = 180.0,
        retry_backoff_sec: float = 0.3,
        retry_max_backoff_sec: float = 2.0,
        retry_jitter_sec: float = 0.15,
        run_budget_max_tokens: int = 24000,
        run_budget_max_duration_sec: float = 300.0,
        run_budget_max_tool_calls: int = 8,
        run_budget_max_tool_errors: int = 3,
        telemetry: TelemetrySink | None = None,
    ) -> None:
        self.logger = logging.getLogger("amaryllis.agents.runs")
        self.database = database
        self.task_executor = task_executor
        self.worker_count = max(1, worker_count)
        self.default_max_attempts = max(1, default_max_attempts)
        self.attempt_timeout_sec = max(5.0, float(attempt_timeout_sec))
        self.retry_backoff_sec = max(0.0, float(retry_backoff_sec))
        self.retry_max_backoff_sec = max(0.0, float(retry_max_backoff_sec))
        self.retry_jitter_sec = max(0.0, float(retry_jitter_sec))
        self.default_run_budget = {
            "max_tokens": max(256, int(run_budget_max_tokens)),
            "max_duration_sec": max(10.0, float(run_budget_max_duration_sec)),
            "max_tool_calls": max(1, int(run_budget_max_tool_calls)),
            "max_tool_errors": max(0, int(run_budget_max_tool_errors)),
        }
        self.telemetry = telemetry

        self._queue: Queue[str | None] = Queue()
        self._workers: list[Thread] = []
        self._stop = Event()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()
        for index in range(self.worker_count):
            worker = Thread(
                target=self._worker_loop,
                name=f"amaryllis-run-worker-{index + 1}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)
        self.logger.info("run_workers_started count=%s", self.worker_count)

    def stop(self) -> None:
        if not self._started:
            return
        self._stop.set()
        for _ in self._workers:
            self._queue.put(None)
        for worker in self._workers:
            worker.join(timeout=2.0)
        self._workers.clear()
        self._started = False
        self.logger.info("run_workers_stopped")

    def create_run(
        self,
        agent: Agent,
        user_id: str,
        session_id: str | None,
        user_message: str,
        max_attempts: int | None = None,
        budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        attempts_limit = max(1, max_attempts or self.default_max_attempts)
        effective_budget = self._normalize_run_budget(budget)
        self.database.create_agent_run(
            run_id=run_id,
            agent_id=agent.id,
            user_id=user_id,
            session_id=session_id,
            input_message=user_message,
            status="queued",
            max_attempts=attempts_limit,
            budget=effective_budget,
        )
        self.database.append_agent_run_checkpoint(
            run_id=run_id,
            checkpoint={
                "stage": "queued",
                "message": "Run queued for execution.",
                "budget": effective_budget,
            },
        )
        self._queue.put(run_id)
        self._emit(
            "agent_run_queued",
            {
                "run_id": run_id,
                "agent_id": agent.id,
                "user_id": user_id,
                "session_id": session_id,
                "max_attempts": attempts_limit,
                "budget": effective_budget,
            },
        )
        run = self.database.get_agent_run(run_id)
        assert run is not None
        return run

    def list_runs(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.database.list_agent_runs(
            user_id=user_id,
            agent_id=agent_id,
            status=status,
            limit=limit,
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.database.get_agent_run(run_id)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self.database.get_agent_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        self.database.update_agent_run_fields(run_id, cancel_requested=1)
        status = str(run.get("status", ""))
        if status == "queued":
            self.database.update_agent_run_fields(
                run_id,
                status="canceled",
                stop_reason="canceled_by_user",
                failure_class="canceled",
                finished_at=self._utc_now(),
            )
            self.database.append_agent_run_checkpoint(
                run_id=run_id,
                checkpoint={
                    "stage": "canceled",
                    "message": "Run canceled before execution.",
                    "stop_reason": "canceled_by_user",
                    "failure_class": "canceled",
                },
            )
        else:
            self.database.append_agent_run_checkpoint(
                run_id=run_id,
                checkpoint={
                    "stage": "cancel_requested",
                    "message": "Cancel requested.",
                    "stop_reason": "cancel_requested",
                },
            )
        updated = self.database.get_agent_run(run_id)
        assert updated is not None
        self._emit(
            "agent_run_canceled",
            {
                "run_id": run_id,
                "status": updated.get("status"),
            },
        )
        return updated

    def resume_run(self, run_id: str) -> dict[str, Any]:
        run = self.database.get_agent_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        status = str(run.get("status", ""))
        if status not in {"failed", "canceled"}:
            raise ValueError(f"Run {run_id} is not resumable (status={status})")
        resume_state = self._extract_resume_state(run)

        self.database.update_agent_run_fields(
            run_id,
            status="queued",
            attempts=0,
            cancel_requested=0,
            error_message=None,
            stop_reason=None,
            failure_class=None,
            metrics_json={},
            started_at=None,
            finished_at=None,
        )
        self.database.append_agent_run_checkpoint(
            run_id=run_id,
            checkpoint={
                "stage": "resumed",
                "message": "Run resumed and queued again.",
                "resume_steps": sorted(resume_state.get("completed_steps", [])) if resume_state else [],
                "resume_state": resume_state or {},
            },
        )
        self._queue.put(run_id)

        updated = self.database.get_agent_run(run_id)
        assert updated is not None
        self._emit(
            "agent_run_resumed",
            {
                "run_id": run_id,
                "status": updated.get("status"),
            },
        )
        return updated

    def replay_run(self, run_id: str) -> dict[str, Any]:
        run = self.database.get_agent_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        raw_checkpoints = run.get("checkpoints")
        checkpoints = raw_checkpoints if isinstance(raw_checkpoints, list) else []

        timeline: list[dict[str, Any]] = []
        attempt_index: dict[int, int] = {}
        attempt_summary: list[dict[str, Any]] = []
        resume_snapshots: list[dict[str, Any]] = []

        for index, item in enumerate(checkpoints):
            if not isinstance(item, dict):
                continue

            timestamp = str(item.get("timestamp", ""))
            stage = str(item.get("stage", "")).strip() or "unknown"
            attempt = self._normalize_attempt(item.get("attempt"))
            message = str(item.get("message", "")).strip()

            event: dict[str, Any] = {
                "index": index + 1,
                "timestamp": timestamp,
                "stage": stage,
                "attempt": attempt,
                "message": message,
            }
            if "retryable" in item:
                event["retryable"] = bool(item.get("retryable"))
            if "failure_class" in item:
                event["failure_class"] = str(item.get("failure_class") or "")
            if "stop_reason" in item:
                event["stop_reason"] = str(item.get("stop_reason") or "")
            timeline.append(event)

            resume_state = item.get("resume_state")
            if isinstance(resume_state, dict):
                completed_steps = resume_state.get("completed_steps")
                resume_snapshots.append(
                    {
                        "timestamp": timestamp,
                        "attempt": attempt,
                        "completed_steps": list(completed_steps) if isinstance(completed_steps, list) else [],
                    }
                )

            if attempt is None:
                continue

            summary_idx = attempt_index.get(attempt)
            if summary_idx is None:
                summary_idx = len(attempt_summary)
                attempt_index[attempt] = summary_idx
                attempt_summary.append(
                    {
                        "attempt": attempt,
                        "stage_counts": {},
                        "started_at": None,
                        "finished_at": None,
                        "tool_rounds": 0,
                        "verification_repairs": 0,
                        "errors": [],
                    }
                )

            summary = attempt_summary[summary_idx]
            stage_counts = summary["stage_counts"]
            assert isinstance(stage_counts, dict)
            stage_counts[stage] = int(stage_counts.get(stage, 0)) + 1

            if stage == "running" and summary.get("started_at") is None:
                summary["started_at"] = timestamp
            if stage in {"succeeded", "failed", "canceled"}:
                summary["finished_at"] = timestamp
            if stage == "tool_call_finished":
                summary["tool_rounds"] = int(summary.get("tool_rounds", 0)) + 1
            if stage == "verification_repair_attempt":
                summary["verification_repairs"] = int(summary.get("verification_repairs", 0)) + 1
            if stage in {"error", "failed"} and message:
                errors = summary["errors"]
                assert isinstance(errors, list)
                errors.append(message)

        latest_resume_state = self._extract_resume_state(run)
        return {
            "run_id": str(run.get("id", run_id)),
            "agent_id": run.get("agent_id"),
            "user_id": run.get("user_id"),
            "session_id": run.get("session_id"),
            "status": run.get("status"),
            "stop_reason": run.get("stop_reason"),
            "failure_class": run.get("failure_class"),
            "attempts": int(run.get("attempts", 0)),
            "max_attempts": int(run.get("max_attempts", 0)),
            "budget": run.get("budget", {}),
            "metrics": run.get("metrics", {}),
            "checkpoint_count": len(timeline),
            "timeline": timeline,
            "attempt_summary": attempt_summary,
            "resume_snapshots": resume_snapshots,
            "latest_resume_state": latest_resume_state or None,
            "has_result": run.get("result") is not None,
            "error_message": run.get("error_message"),
        }

    def get_run_health(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        runs = self.database.list_agent_runs(
            user_id=user_id,
            agent_id=agent_id,
            status=None,
            limit=max(1, min(int(limit), 2000)),
        )
        total_runs = len(runs)
        terminal = [item for item in runs if str(item.get("status", "")).lower() in {"succeeded", "failed", "canceled"}]
        succeeded = sum(1 for item in terminal if str(item.get("status", "")).lower() == "succeeded")
        failed = sum(1 for item in terminal if str(item.get("status", "")).lower() == "failed")
        canceled = sum(1 for item in terminal if str(item.get("status", "")).lower() == "canceled")
        retry_runs = sum(1 for item in terminal if int(item.get("attempts", 0)) > 1)

        run_durations_ms: list[float] = []
        attempts_per_run: list[int] = []
        stop_reason_counts: dict[str, int] = {}
        failure_class_counts: dict[str, int] = {}
        run_attempt_durations_ms: list[float] = []
        run_attempt_successes = 0
        run_attempt_total = 0
        tool_call_durations_ms: list[float] = []
        tool_call_successes = 0
        tool_call_total = 0
        verification_repair_total = 0

        for run in runs:
            attempts_per_run.append(max(0, int(run.get("attempts", 0))))
            stop_reason = str(run.get("stop_reason") or "").strip() or "none"
            failure_class = str(run.get("failure_class") or "").strip() or "none"
            stop_reason_counts[stop_reason] = int(stop_reason_counts.get(stop_reason, 0)) + 1
            failure_class_counts[failure_class] = int(failure_class_counts.get(failure_class, 0)) + 1

            duration = self._duration_ms(started_at=run.get("started_at"), finished_at=run.get("finished_at"))
            if duration is not None:
                run_durations_ms.append(duration)

            checkpoints = run.get("checkpoints")
            if not isinstance(checkpoints, list):
                continue

            running_by_attempt: dict[int, str] = {}
            terminal_by_attempt: dict[int, str] = {}
            terminal_stage_by_attempt: dict[int, str] = {}

            for item in checkpoints:
                if not isinstance(item, dict):
                    continue
                stage = str(item.get("stage", "")).strip()
                attempt = self._normalize_attempt(item.get("attempt"))
                timestamp = str(item.get("timestamp", "")).strip()

                if attempt is not None and stage == "running":
                    running_by_attempt.setdefault(attempt, timestamp)
                if attempt is not None and stage in {"succeeded", "failed", "canceled"}:
                    terminal_by_attempt[attempt] = timestamp
                    terminal_stage_by_attempt[attempt] = stage
                if stage == "tool_call_finished":
                    tool_call_total += 1
                    status = str(item.get("status", "")).strip().lower()
                    if status == "succeeded":
                        tool_call_successes += 1
                    try:
                        duration_ms = float(item.get("duration_ms", 0.0))
                    except Exception:
                        duration_ms = 0.0
                    if duration_ms > 0:
                        tool_call_durations_ms.append(duration_ms)
                if stage == "verification_repair_attempt":
                    verification_repair_total += 1

            for attempt, started_at in running_by_attempt.items():
                finished_at = terminal_by_attempt.get(attempt)
                if not finished_at:
                    continue
                attempt_duration = self._duration_ms(started_at=started_at, finished_at=finished_at)
                if attempt_duration is not None:
                    run_attempt_durations_ms.append(attempt_duration)
                run_attempt_total += 1
                if terminal_stage_by_attempt.get(attempt) == "succeeded":
                    run_attempt_successes += 1

        terminal_count = len(terminal)
        success_rate = (succeeded / terminal_count) if terminal_count else 0.0
        retry_rate = (retry_runs / terminal_count) if terminal_count else 0.0

        return {
            "sample_size": total_runs,
            "terminal_runs": terminal_count,
            "status_breakdown": {
                "succeeded": succeeded,
                "failed": failed,
                "canceled": canceled,
            },
            "success_rate": round(success_rate, 6),
            "retry_rate": round(retry_rate, 6),
            "stop_reason_breakdown": stop_reason_counts,
            "failure_class_breakdown": failure_class_counts,
            "slo": {
                "run": {
                    "success_rate": round(success_rate, 6),
                    "retry_rate": round(retry_rate, 6),
                    "duration_ms": self._distribution(run_durations_ms),
                    "attempts_per_run": self._distribution([float(item) for item in attempts_per_run]),
                },
                "run_attempt": {
                    "count": run_attempt_total,
                    "success_rate": round((run_attempt_successes / run_attempt_total), 6)
                    if run_attempt_total
                    else 0.0,
                    "duration_ms": self._distribution(run_attempt_durations_ms),
                },
                "tool_call": {
                    "count": tool_call_total,
                    "success_rate": round((tool_call_successes / tool_call_total), 6) if tool_call_total else 0.0,
                    "duration_ms": self._distribution(tool_call_durations_ms),
                },
                "verification": {
                    "repair_attempts": verification_repair_total,
                },
            },
        }

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except Empty:
                continue

            if item is None:
                self._queue.task_done()
                break

            try:
                self._process_run(item)
            except Exception as exc:
                self.logger.exception("run_worker_unhandled run_id=%s error=%s", item, exc)
            finally:
                self._queue.task_done()

    def _process_run(self, run_id: str) -> None:
        run = self.database.get_agent_run(run_id)
        if run is None:
            return

        budget = self._normalize_run_budget(run.get("budget"))
        metrics_base = self._normalize_run_metrics(run.get("metrics"))

        if int(run.get("cancel_requested", 0)) == 1:
            self.database.update_agent_run_fields(
                run_id,
                status="canceled",
                stop_reason="canceled_by_user",
                failure_class="canceled",
                metrics_json=metrics_base,
                finished_at=self._utc_now(),
            )
            self.database.append_agent_run_checkpoint(
                run_id=run_id,
                checkpoint={
                    "stage": "canceled",
                    "message": "Run canceled before worker execution.",
                    "stop_reason": "canceled_by_user",
                    "failure_class": "canceled",
                },
            )
            return

        status = str(run.get("status", ""))
        if status not in {"queued", "running"}:
            return

        agent_record = self.database.get_agent(str(run["agent_id"]))
        if agent_record is None:
            self.database.update_agent_run_fields(
                run_id,
                status="failed",
                stop_reason="agent_not_found",
                failure_class="not_found",
                error_message=f"Agent not found: {run['agent_id']}",
                metrics_json=metrics_base,
                finished_at=self._utc_now(),
            )
            self.database.append_agent_run_checkpoint(
                run_id=run_id,
                checkpoint={
                    "stage": "failed",
                    "message": f"Agent not found: {run['agent_id']}",
                    "stop_reason": "agent_not_found",
                    "failure_class": "not_found",
                    "retryable": False,
                },
            )
            return

        agent = Agent.from_record(agent_record)
        attempt = int(run.get("attempts", 0)) + 1
        max_attempts = int(run.get("max_attempts", self.default_max_attempts))
        started_at = str(run.get("started_at") or "").strip()
        if not started_at:
            started_at = self._utc_now()
        if self._remaining_duration_sec(started_at=started_at, budget=budget) <= 0.0:
            error_message = "Run duration budget exceeded before attempt start."
            metrics_final = self._finalize_run_metrics(
                metrics=metrics_base,
                attempt=attempt,
                attempt_duration_ms=0.0,
            )
            self.database.update_agent_run_fields(
                run_id,
                status="failed",
                stop_reason="budget_exceeded",
                failure_class="budget_exceeded",
                error_message=error_message,
                metrics_json=metrics_final,
                finished_at=self._utc_now(),
            )
            self.database.append_agent_run_checkpoint(
                run_id=run_id,
                checkpoint={
                    "stage": "failed",
                    "attempt": attempt,
                    "message": error_message,
                    "retryable": False,
                    "stop_reason": "budget_exceeded",
                    "failure_class": "budget_exceeded",
                },
            )
            return

        self.database.update_agent_run_fields(
            run_id,
            status="running",
            attempts=attempt,
            started_at=started_at,
            stop_reason=None,
            failure_class=None,
            error_message=None,
            metrics_json=metrics_base,
        )
        self.database.append_agent_run_checkpoint(
            run_id=run_id,
            checkpoint={
                "stage": "running",
                "attempt": attempt,
                "message": f"Execution started (attempt {attempt}/{max_attempts}).",
                "attempt_timeout_sec": self.attempt_timeout_sec,
                "run_budget": budget,
                "metrics_baseline": metrics_base,
            },
        )

        attempt_started_monotonic = time.monotonic()
        live_usage = {
            "estimated_tokens": int(metrics_base.get("estimated_tokens", 0)),
            "tool_calls": int(metrics_base.get("tool_calls", 0)),
            "tool_errors": int(metrics_base.get("tool_errors", 0)),
        }

        try:
            def push_checkpoint(payload: dict[str, Any]) -> None:
                data = dict(payload)
                data.setdefault("attempt", attempt)
                self._merge_checkpoint_usage(live_usage=live_usage, checkpoint=data)
                self._validate_live_budget_usage(budget=budget, usage=live_usage)
                self.database.append_agent_run_checkpoint(run_id=run_id, checkpoint=data)

            resume_state = self._extract_resume_state(run)
            result = self._run_task_executor(
                run=run,
                agent=agent,
                attempt=attempt,
                started_at=started_at,
                budget=budget,
                checkpoint=push_checkpoint,
                resume_state=resume_state,
            )
        except Exception as exc:
            error_message = str(exc)
            failure = self._classify_failure(exc)
            retryable = bool(failure.get("retryable", False))
            failure_class = str(failure.get("failure_class", "unknown"))
            stop_reason = str(failure.get("stop_reason", "unknown_error"))
            attempt_duration_ms = round((time.monotonic() - attempt_started_monotonic) * 1000.0, 2)
            metrics_after_error = self._finalize_run_metrics(
                metrics=live_usage,
                attempt=attempt,
                attempt_duration_ms=attempt_duration_ms,
            )
            self.database.append_agent_run_checkpoint(
                run_id=run_id,
                checkpoint={
                    "stage": "error",
                    "attempt": attempt,
                    "message": error_message,
                    "retryable": retryable,
                    "failure_class": failure_class,
                    "stop_reason": stop_reason,
                    "estimated_tokens_total": metrics_after_error["estimated_tokens"],
                    "tool_calls_total": metrics_after_error["tool_calls"],
                    "tool_errors_total": metrics_after_error["tool_errors"],
                },
            )

            if attempt < max_attempts and int(run.get("cancel_requested", 0)) != 1 and retryable:
                backoff_sec = self._retry_delay_seconds(attempt=attempt)
                self.database.update_agent_run_fields(
                    run_id,
                    status="queued",
                    error_message=error_message,
                    stop_reason=stop_reason,
                    failure_class=failure_class,
                    metrics_json=metrics_after_error,
                )
                self.database.append_agent_run_checkpoint(
                    run_id=run_id,
                    checkpoint={
                        "stage": "retry_scheduled",
                        "attempt": attempt + 1,
                        "message": "Retry scheduled.",
                        "backoff_sec": backoff_sec,
                        "retryable": retryable,
                        "failure_class": failure_class,
                        "stop_reason": stop_reason,
                    },
                )
                if backoff_sec > 0:
                    time.sleep(backoff_sec)
                self._queue.put(run_id)
            else:
                canceled = int(run.get("cancel_requested", 0)) == 1
                final_status = "canceled" if canceled else "failed"
                final_failure_class = "canceled" if canceled else failure_class
                final_stop_reason = "canceled_by_user" if canceled else stop_reason
                if not canceled and retryable and attempt >= max_attempts:
                    final_stop_reason = "max_attempts_exhausted"
                self.database.update_agent_run_fields(
                    run_id,
                    status=final_status,
                    error_message=error_message,
                    stop_reason=final_stop_reason,
                    failure_class=final_failure_class,
                    metrics_json=metrics_after_error,
                    finished_at=self._utc_now(),
                )
                self.database.append_agent_run_checkpoint(
                    run_id=run_id,
                    checkpoint={
                        "stage": final_status,
                        "attempt": attempt,
                        "message": error_message,
                        "retryable": retryable,
                        "failure_class": final_failure_class,
                        "stop_reason": final_stop_reason,
                    },
                )
            return

        latest = self.database.get_agent_run(run_id)
        metrics_final = self._extract_result_metrics(result=result, fallback=live_usage, attempt=attempt)
        if latest is not None and int(latest.get("cancel_requested", 0)) == 1:
            self.database.update_agent_run_fields(
                run_id,
                status="canceled",
                stop_reason="canceled_by_user",
                failure_class="canceled",
                result_json=result,
                metrics_json=metrics_final,
                finished_at=self._utc_now(),
            )
            self.database.append_agent_run_checkpoint(
                run_id=run_id,
                checkpoint={
                    "stage": "canceled",
                    "attempt": attempt,
                    "message": "Execution completed but run was canceled.",
                    "failure_class": "canceled",
                    "stop_reason": "canceled_by_user",
                },
            )
            return

        self.database.update_agent_run_fields(
            run_id,
            status="succeeded",
            stop_reason="completed",
            failure_class=None,
            result_json=result,
            error_message=None,
            metrics_json=metrics_final,
            finished_at=self._utc_now(),
        )
        self.database.append_agent_run_checkpoint(
            run_id=run_id,
            checkpoint={
                "stage": "succeeded",
                "attempt": attempt,
                "message": "Execution completed successfully.",
                "stop_reason": "completed",
                "metrics": metrics_final,
            },
        )
        self._emit(
            "agent_run_succeeded",
            {
                "run_id": run_id,
                "agent_id": agent.id,
                "attempts": attempt,
                "metrics": metrics_final,
                "budget": budget,
            },
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.telemetry is None:
            return
        try:
            self.telemetry.emit(event_type, payload)
        except Exception:
            self.logger.debug("run_telemetry_emit_failed event=%s", event_type)

    def _run_task_executor(
        self,
        *,
        run: dict[str, Any],
        agent: Agent,
        attempt: int,
        started_at: str,
        budget: dict[str, Any],
        checkpoint: Any,
        resume_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempt_started = time.monotonic()
        attempt_deadline = attempt_started + self.attempt_timeout_sec
        remaining_duration = self._remaining_duration_sec(started_at=started_at, budget=budget)
        if remaining_duration <= 0.0:
            raise RunBudgetExceededError("Run duration budget exceeded.")
        attempt_deadline = min(attempt_deadline, attempt_started + remaining_duration)
        result: dict[str, Any]
        try:
            result = self.task_executor.execute(
                agent=agent,
                user_id=str(run["user_id"]),
                session_id=run.get("session_id"),
                user_message=str(run["input_message"]),
                checkpoint=checkpoint,
                run_deadline_monotonic=attempt_deadline,
                resume_state=resume_state,
                run_budget=budget,
            )
        except TypeError as exc:
            # Backward compatibility for custom executors used in tests/tools.
            message = str(exc)
            if "run_budget" in message and "resume_state" in message and "run_deadline_monotonic" in message:
                result = self.task_executor.execute(
                    agent=agent,
                    user_id=str(run["user_id"]),
                    session_id=run.get("session_id"),
                    user_message=str(run["input_message"]),
                    checkpoint=checkpoint,
                )
            elif "run_budget" in message and "resume_state" in message:
                result = self.task_executor.execute(
                    agent=agent,
                    user_id=str(run["user_id"]),
                    session_id=run.get("session_id"),
                    user_message=str(run["input_message"]),
                    checkpoint=checkpoint,
                    run_deadline_monotonic=attempt_deadline,
                )
            elif "run_budget" in message and "run_deadline_monotonic" in message:
                result = self.task_executor.execute(
                    agent=agent,
                    user_id=str(run["user_id"]),
                    session_id=run.get("session_id"),
                    user_message=str(run["input_message"]),
                    checkpoint=checkpoint,
                    resume_state=resume_state,
                )
            elif "run_budget" in message:
                result = self.task_executor.execute(
                    agent=agent,
                    user_id=str(run["user_id"]),
                    session_id=run.get("session_id"),
                    user_message=str(run["input_message"]),
                    checkpoint=checkpoint,
                    run_deadline_monotonic=attempt_deadline,
                    resume_state=resume_state,
                )
            elif "resume_state" in message and "run_deadline_monotonic" in message:
                result = self.task_executor.execute(
                    agent=agent,
                    user_id=str(run["user_id"]),
                    session_id=run.get("session_id"),
                    user_message=str(run["input_message"]),
                    checkpoint=checkpoint,
                )
            elif "resume_state" in message:
                try:
                    result = self.task_executor.execute(
                        agent=agent,
                        user_id=str(run["user_id"]),
                        session_id=run.get("session_id"),
                        user_message=str(run["input_message"]),
                        checkpoint=checkpoint,
                        run_deadline_monotonic=attempt_deadline,
                    )
                except TypeError as nested_exc:
                    if "run_deadline_monotonic" not in str(nested_exc):
                        raise
                    result = self.task_executor.execute(
                        agent=agent,
                        user_id=str(run["user_id"]),
                        session_id=run.get("session_id"),
                        user_message=str(run["input_message"]),
                        checkpoint=checkpoint,
                    )
            elif "run_deadline_monotonic" in message:
                try:
                    result = self.task_executor.execute(
                        agent=agent,
                        user_id=str(run["user_id"]),
                        session_id=run.get("session_id"),
                        user_message=str(run["input_message"]),
                        checkpoint=checkpoint,
                        resume_state=resume_state,
                    )
                except TypeError as nested_exc:
                    if "resume_state" not in str(nested_exc):
                        raise
                    result = self.task_executor.execute(
                        agent=agent,
                        user_id=str(run["user_id"]),
                        session_id=run.get("session_id"),
                        user_message=str(run["input_message"]),
                        checkpoint=checkpoint,
                    )
            else:
                raise
        elapsed = time.monotonic() - attempt_started
        if elapsed > self.attempt_timeout_sec:
            self.database.append_agent_run_checkpoint(
                run_id=str(run["id"]),
                checkpoint={
                    "stage": "attempt_timeout_guardrail",
                    "attempt": attempt,
                    "message": (
                        f"Attempt exceeded timeout: elapsed={elapsed:.2f}s "
                        f"limit={self.attempt_timeout_sec:.2f}s"
                    ),
                },
            )
            raise TaskTimeoutError(
                f"Run attempt exceeded timeout ({elapsed:.2f}s > {self.attempt_timeout_sec:.2f}s)."
            )
        return result

    def _classify_failure(self, exc: Exception) -> dict[str, Any]:
        if isinstance(exc, RunBudgetExceededError):
            return {
                "failure_class": "budget_exceeded",
                "stop_reason": "budget_exceeded",
                "retryable": False,
            }
        if isinstance(exc, TaskTimeoutError):
            return {
                "failure_class": "timeout",
                "stop_reason": "timeout",
                "retryable": True,
            }
        if isinstance(exc, TaskGuardrailError):
            message = str(exc).lower()
            if "budget" in message:
                return {
                    "failure_class": "budget_exceeded",
                    "stop_reason": "budget_exceeded",
                    "retryable": False,
                }
            return {
                "failure_class": "guardrail",
                "stop_reason": "guardrail_rejected",
                "retryable": False,
            }
        if isinstance(exc, ProviderOperationError):
            error_class = str(exc.info.error_class)
            return {
                "failure_class": error_class,
                "stop_reason": f"provider_{error_class}",
                "retryable": error_class in RUN_RETRYABLE_FAILURE_CLASSES,
            }
        if isinstance(exc, (ValueError, TypeError, AssertionError)):
            return {
                "failure_class": "invalid_request",
                "stop_reason": "invalid_request",
                "retryable": False,
            }

        provider_info = classify_provider_error(
            provider="unknown",
            operation="agent_run",
            error=exc,
        )
        provider_class = str(provider_info.error_class)
        if provider_class != "unknown":
            return {
                "failure_class": provider_class,
                "stop_reason": f"provider_{provider_class}",
                "retryable": provider_class in RUN_RETRYABLE_FAILURE_CLASSES,
            }

        return {
            "failure_class": "unknown",
            "stop_reason": "unknown_error",
            "retryable": False,
        }

    def _normalize_run_budget(self, budget: dict[str, Any] | None) -> dict[str, Any]:
        raw = budget if isinstance(budget, dict) else {}
        return {
            "max_tokens": max(
                256,
                self._safe_int(raw.get("max_tokens", self.default_run_budget["max_tokens"]), 256),
            ),
            "max_duration_sec": max(
                10.0,
                self._safe_float(raw.get("max_duration_sec", self.default_run_budget["max_duration_sec"]), 10.0),
            ),
            "max_tool_calls": max(
                1,
                self._safe_int(raw.get("max_tool_calls", self.default_run_budget["max_tool_calls"]), 1),
            ),
            "max_tool_errors": max(
                0,
                self._safe_int(raw.get("max_tool_errors", self.default_run_budget["max_tool_errors"]), 0),
            ),
        }

    @staticmethod
    def _normalize_run_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
        source = metrics if isinstance(metrics, dict) else {}
        return {
            "estimated_tokens": max(0, AgentRunManager._safe_int(source.get("estimated_tokens", 0), 0)),
            "tool_calls": max(0, AgentRunManager._safe_int(source.get("tool_calls", 0), 0)),
            "tool_errors": max(0, AgentRunManager._safe_int(source.get("tool_errors", 0), 0)),
            "attempt_count": max(0, AgentRunManager._safe_int(source.get("attempt_count", 0), 0)),
            "retry_count": max(0, AgentRunManager._safe_int(source.get("retry_count", 0), 0)),
            "total_attempt_duration_ms": max(
                0.0,
                AgentRunManager._safe_float(source.get("total_attempt_duration_ms", 0.0), 0.0),
            ),
            "last_attempt_duration_ms": max(
                0.0,
                AgentRunManager._safe_float(source.get("last_attempt_duration_ms", 0.0), 0.0),
            ),
        }

    def _finalize_run_metrics(
        self,
        *,
        metrics: dict[str, Any],
        attempt: int,
        attempt_duration_ms: float,
    ) -> dict[str, Any]:
        normalized = self._normalize_run_metrics(metrics)
        normalized["attempt_count"] = max(int(normalized.get("attempt_count", 0)), int(attempt))
        normalized["retry_count"] = max(0, int(normalized["attempt_count"]) - 1)
        normalized["last_attempt_duration_ms"] = max(0.0, float(attempt_duration_ms))
        normalized["total_attempt_duration_ms"] = round(
            max(0.0, float(normalized.get("total_attempt_duration_ms", 0.0))) + max(0.0, float(attempt_duration_ms)),
            3,
        )
        return normalized

    @staticmethod
    def _merge_checkpoint_usage(*, live_usage: dict[str, Any], checkpoint: dict[str, Any]) -> None:
        if "estimated_tokens_total" in checkpoint:
            try:
                tokens_total = max(0, int(checkpoint.get("estimated_tokens_total", 0)))
                live_usage["estimated_tokens"] = max(int(live_usage.get("estimated_tokens", 0)), tokens_total)
            except Exception:
                pass
        stage = str(checkpoint.get("stage", "")).strip()
        if stage == "tool_call_finished":
            live_usage["tool_calls"] = max(0, int(live_usage.get("tool_calls", 0))) + 1
            status = str(checkpoint.get("status", "")).strip().lower()
            if status in {"failed", "invalid_arguments", "blocked", "permission_required"}:
                live_usage["tool_errors"] = max(0, int(live_usage.get("tool_errors", 0))) + 1

    @staticmethod
    def _validate_live_budget_usage(*, budget: dict[str, Any], usage: dict[str, Any]) -> None:
        max_tokens = int(budget.get("max_tokens", 0))
        max_tool_calls = int(budget.get("max_tool_calls", 0))
        max_tool_errors = int(budget.get("max_tool_errors", 0))
        estimated_tokens = int(usage.get("estimated_tokens", 0))
        tool_calls = int(usage.get("tool_calls", 0))
        tool_errors = int(usage.get("tool_errors", 0))
        if max_tokens > 0 and estimated_tokens > max_tokens:
            raise RunBudgetExceededError(
                f"Run token budget exceeded ({estimated_tokens} > {max_tokens})."
            )
        if max_tool_calls > 0 and tool_calls > max_tool_calls:
            raise RunBudgetExceededError(
                f"Run tool-call budget exceeded ({tool_calls} > {max_tool_calls})."
            )
        if max_tool_errors >= 0 and tool_errors > max_tool_errors:
            raise RunBudgetExceededError(
                f"Run tool-error budget exceeded ({tool_errors} > {max_tool_errors})."
            )

    def _extract_result_metrics(
        self,
        *,
        result: dict[str, Any],
        fallback: dict[str, Any],
        attempt: int,
    ) -> dict[str, Any]:
        metrics = result.get("metrics")
        if not isinstance(metrics, dict):
            return self._finalize_run_metrics(
                metrics=fallback,
                attempt=attempt,
                attempt_duration_ms=0.0,
            )
        merged = {
            "estimated_tokens": max(
                0,
                self._safe_int(metrics.get("estimated_tokens", fallback.get("estimated_tokens", 0)), 0),
            ),
            "tool_calls": max(
                0,
                self._safe_int(metrics.get("tool_calls", fallback.get("tool_calls", 0)), 0),
            ),
            "tool_errors": max(
                0,
                self._safe_int(metrics.get("tool_errors", fallback.get("tool_errors", 0)), 0),
            ),
            "attempt_count": max(self._safe_int(metrics.get("attempt_count", attempt), attempt), int(attempt)),
            "retry_count": max(0, self._safe_int(metrics.get("attempt_count", attempt), attempt) - 1),
            "total_attempt_duration_ms": max(
                0.0,
                self._safe_float(
                    metrics.get("total_attempt_duration_ms", metrics.get("duration_ms", 0.0)),
                    0.0,
                ),
            ),
            "last_attempt_duration_ms": max(0.0, self._safe_float(metrics.get("duration_ms", 0.0), 0.0)),
        }
        return self._normalize_run_metrics(merged)

    def _remaining_duration_sec(self, *, started_at: str, budget: dict[str, Any]) -> float:
        max_duration_sec = max(0.0, float(budget.get("max_duration_sec", 0.0)))
        if max_duration_sec <= 0:
            return 0.0
        start_dt = self._parse_iso_datetime(started_at)
        if start_dt is None:
            return max_duration_sec
        elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
        return max(0.0, max_duration_sec - max(0.0, elapsed))

    def _retry_delay_seconds(self, *, attempt: int) -> float:
        if self.retry_backoff_sec <= 0:
            return 0.0
        exponential = self.retry_backoff_sec * (2 ** max(0, attempt - 1))
        bounded = min(exponential, self.retry_max_backoff_sec) if self.retry_max_backoff_sec > 0 else exponential
        jitter = random.uniform(0.0, self.retry_jitter_sec) if self.retry_jitter_sec > 0 else 0.0
        return round(max(0.0, bounded + jitter), 3)

    @classmethod
    def _distribution(cls, values: list[float]) -> dict[str, float]:
        if not values:
            return {"count": 0.0, "min": 0.0, "max": 0.0, "median": 0.0, "p95": 0.0}
        normalized = sorted(max(0.0, float(item)) for item in values)
        return {
            "count": float(len(normalized)),
            "min": round(normalized[0], 3),
            "max": round(normalized[-1], 3),
            "median": round(cls._percentile(normalized, 50), 3),
            "p95": round(cls._percentile(normalized, 95), 3),
        }

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return float(values[0])
        position = max(0.0, min(100.0, float(percentile))) / 100.0 * (len(values) - 1)
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        weight = position - lower
        return float(values[lower] * (1.0 - weight) + values[upper] * weight)

    @classmethod
    def _duration_ms(cls, *, started_at: Any, finished_at: Any) -> float | None:
        start_dt = cls._parse_iso_datetime(started_at)
        finish_dt = cls._parse_iso_datetime(finished_at)
        if start_dt is None or finish_dt is None:
            return None
        delta = (finish_dt - start_dt).total_seconds() * 1000.0
        if delta < 0:
            return 0.0
        return round(delta, 3)

    @staticmethod
    def _parse_iso_datetime(value: Any) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _extract_resume_state(run: dict[str, Any]) -> dict[str, Any] | None:
        checkpoints = run.get("checkpoints")
        if not isinstance(checkpoints, list):
            return None
        for item in reversed(checkpoints):
            if not isinstance(item, dict):
                continue
            payload = item.get("resume_state")
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _normalize_attempt(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
