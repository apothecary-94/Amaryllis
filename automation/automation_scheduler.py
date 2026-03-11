from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Event, Thread
from typing import Any, Protocol
from uuid import uuid4

from agents.agent import Agent
from agents.agent_run_manager import AgentRunManager
from automation.schedule import compute_next_run_at, normalize_schedule, validate_timezone
from storage.database import Database


class TelemetrySink(Protocol):
    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        ...


class AutomationScheduler:
    def __init__(
        self,
        database: Database,
        run_manager: AgentRunManager,
        poll_interval_sec: float = 2.0,
        batch_size: int = 10,
        telemetry: TelemetrySink | None = None,
    ) -> None:
        self.logger = logging.getLogger("amaryllis.automation.scheduler")
        self.database = database
        self.run_manager = run_manager
        self.poll_interval_sec = max(0.5, float(poll_interval_sec))
        self.batch_size = max(1, int(batch_size))
        self.telemetry = telemetry

        self._thread: Thread | None = None
        self._stop = Event()
        self._started = False

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _utc_now_iso(cls) -> str:
        return cls._utc_now().isoformat()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="amaryllis-automation-scheduler", daemon=True)
        self._thread.start()
        self.logger.info(
            "automation_scheduler_started poll_interval_sec=%s batch_size=%s",
            self.poll_interval_sec,
            self.batch_size,
        )

    def stop(self) -> None:
        if not self._started:
            return
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._started = False
        self.logger.info("automation_scheduler_stopped")

    def create_automation(
        self,
        *,
        agent_id: str,
        user_id: str,
        session_id: str | None,
        message: str,
        interval_sec: int | None = None,
        schedule_type: str | None = None,
        schedule: dict[str, Any] | None = None,
        timezone_name: str = "UTC",
        start_immediately: bool = False,
    ) -> dict[str, Any]:
        automation_id = str(uuid4())
        normalized_type, normalized_schedule, normalized_interval = normalize_schedule(
            schedule_type=schedule_type,
            schedule=schedule,
            interval_sec=interval_sec,
        )
        normalized_timezone = validate_timezone(timezone_name)

        now = self._utc_now()
        next_run_at = (
            now.isoformat()
            if start_immediately
            else compute_next_run_at(
                schedule_type=normalized_type,
                schedule=normalized_schedule,
                timezone_name=normalized_timezone,
                now_utc=now,
            )
        )

        self.database.create_automation(
            automation_id=automation_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            message=message,
            interval_sec=normalized_interval,
            next_run_at=next_run_at,
            schedule_type=normalized_type,
            schedule=normalized_schedule,
            timezone_name=normalized_timezone,
        )
        self.database.add_automation_event(
            automation_id=automation_id,
            event_type="created",
            message=(
                f"Automation created "
                f"(schedule_type={normalized_type}, timezone={normalized_timezone})."
            ),
        )
        self._emit(
            "automation_created",
            {
                "automation_id": automation_id,
                "agent_id": agent_id,
                "user_id": user_id,
                "schedule_type": normalized_type,
                "timezone": normalized_timezone,
            },
        )
        created = self.database.get_automation(automation_id)
        assert created is not None
        return created

    def update_automation(
        self,
        automation_id: str,
        *,
        message: str | None = None,
        session_id: str | None = None,
        interval_sec: int | None = None,
        schedule_type: str | None = None,
        schedule: dict[str, Any] | None = None,
        timezone_name: str | None = None,
    ) -> dict[str, Any]:
        automation = self.database.get_automation(automation_id)
        if automation is None:
            raise ValueError(f"Automation not found: {automation_id}")

        current_type = str(automation.get("schedule_type", "interval"))
        current_schedule = automation.get("schedule")
        if not isinstance(current_schedule, dict):
            current_schedule = {}
        current_interval = int(automation.get("interval_sec", 300))

        normalized_type, normalized_schedule, normalized_interval = normalize_schedule(
            schedule_type=schedule_type or current_type,
            schedule=schedule if schedule is not None else current_schedule,
            interval_sec=interval_sec if interval_sec is not None else current_interval,
        )
        normalized_timezone = validate_timezone(timezone_name or str(automation.get("timezone", "UTC")))

        updates: dict[str, Any] = {
            "interval_sec": normalized_interval,
            "schedule_type": normalized_type,
            "schedule_json": normalized_schedule,
            "timezone": normalized_timezone,
            "last_error": None,
        }
        if message is not None:
            updates["message"] = message
        if session_id is not None:
            updates["session_id"] = session_id

        if bool(automation.get("is_enabled", False)):
            updates["next_run_at"] = compute_next_run_at(
                schedule_type=normalized_type,
                schedule=normalized_schedule,
                timezone_name=normalized_timezone,
                now_utc=self._utc_now(),
            )

        self.database.update_automation_fields(automation_id, **updates)
        self.database.add_automation_event(
            automation_id=automation_id,
            event_type="updated",
            message=(
                f"Automation updated "
                f"(schedule_type={normalized_type}, timezone={normalized_timezone})."
            ),
        )
        updated = self.database.get_automation(automation_id)
        assert updated is not None
        return updated

    def list_automations(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        enabled: bool | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self.database.list_automations(
            user_id=user_id,
            agent_id=agent_id,
            enabled=enabled,
            limit=limit,
        )

    def get_automation(self, automation_id: str) -> dict[str, Any] | None:
        return self.database.get_automation(automation_id)

    def pause_automation(self, automation_id: str) -> dict[str, Any]:
        automation = self.database.get_automation(automation_id)
        if automation is None:
            raise ValueError(f"Automation not found: {automation_id}")

        self.database.update_automation_fields(
            automation_id,
            is_enabled=False,
        )
        self.database.add_automation_event(
            automation_id=automation_id,
            event_type="paused",
            message="Automation paused.",
        )
        updated = self.database.get_automation(automation_id)
        assert updated is not None
        return updated

    def resume_automation(self, automation_id: str) -> dict[str, Any]:
        automation = self.database.get_automation(automation_id)
        if automation is None:
            raise ValueError(f"Automation not found: {automation_id}")

        schedule_type, schedule, _ = self._normalized_schedule_from_row(automation)
        timezone_name = validate_timezone(str(automation.get("timezone", "UTC")))
        next_run_at = compute_next_run_at(
            schedule_type=schedule_type,
            schedule=schedule,
            timezone_name=timezone_name,
            now_utc=self._utc_now(),
        )
        self.database.update_automation_fields(
            automation_id,
            is_enabled=True,
            next_run_at=next_run_at,
            last_error=None,
        )
        self.database.add_automation_event(
            automation_id=automation_id,
            event_type="resumed",
            message="Automation resumed.",
        )
        updated = self.database.get_automation(automation_id)
        assert updated is not None
        return updated

    def run_now(self, automation_id: str) -> dict[str, Any]:
        automation = self.database.get_automation(automation_id)
        if automation is None:
            raise ValueError(f"Automation not found: {automation_id}")
        self._trigger(automation, source="manual")
        updated = self.database.get_automation(automation_id)
        assert updated is not None
        return updated

    def delete_automation(self, automation_id: str) -> bool:
        automation = self.database.get_automation(automation_id)
        if automation is None:
            return False
        return self.database.delete_automation(automation_id)

    def list_events(self, automation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.database.list_automation_events(automation_id=automation_id, limit=limit)

    def _normalized_schedule_from_row(self, automation: dict[str, Any]) -> tuple[str, dict[str, Any], int]:
        row_schedule = automation.get("schedule")
        if not isinstance(row_schedule, dict):
            row_schedule = {}
        return normalize_schedule(
            schedule_type=str(automation.get("schedule_type", "interval")),
            schedule=row_schedule,
            interval_sec=int(automation.get("interval_sec", 300)),
        )

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                self.logger.exception("automation_scheduler_tick_failed error=%s", exc)
            self._stop.wait(self.poll_interval_sec)

    def _tick(self) -> None:
        now_iso = self._utc_now_iso()
        due_items = self.database.list_due_automations(now_iso=now_iso, limit=self.batch_size)
        if not due_items:
            return
        for automation in due_items:
            try:
                self._trigger(automation, source="scheduled")
            except Exception as exc:
                self.logger.error(
                    "automation_trigger_failed automation_id=%s error=%s",
                    automation.get("id"),
                    exc,
                )

    def _trigger(self, automation: dict[str, Any], *, source: str) -> None:
        automation_id = str(automation["id"])
        schedule_type, schedule, interval_sec = self._normalized_schedule_from_row(automation)
        timezone_name = validate_timezone(str(automation.get("timezone", "UTC")))
        now = self._utc_now()
        now_iso = now.isoformat()

        next_run_at = compute_next_run_at(
            schedule_type=schedule_type,
            schedule=schedule,
            timezone_name=timezone_name,
            now_utc=now,
        )

        try:
            agent_record = self.database.get_agent(str(automation["agent_id"]))
            if agent_record is None:
                raise ValueError(f"Agent not found: {automation['agent_id']}")

            run = self.run_manager.create_run(
                agent=Agent.from_record(agent_record),
                user_id=str(automation["user_id"]),
                session_id=automation.get("session_id"),
                user_message=str(automation["message"]),
            )
            run_id = str(run["id"])
            self.database.update_automation_fields(
                automation_id,
                last_run_at=now_iso,
                next_run_at=next_run_at,
                last_error=None,
                interval_sec=interval_sec,
                schedule_type=schedule_type,
                schedule_json=schedule,
                timezone=timezone_name,
            )
            self.database.add_automation_event(
                automation_id=automation_id,
                event_type="run_queued",
                message=f"Automation queued run ({source}).",
                run_id=run_id,
            )
            self._emit(
                "automation_run_queued",
                {
                    "automation_id": automation_id,
                    "run_id": run_id,
                    "source": source,
                    "schedule_type": schedule_type,
                },
            )
        except Exception as exc:
            error = str(exc)
            retry_next = compute_next_run_at(
                schedule_type="interval",
                schedule={"interval_sec": max(interval_sec, 30)},
                timezone_name=timezone_name,
                now_utc=now,
            )
            self.database.update_automation_fields(
                automation_id,
                last_error=error,
                next_run_at=retry_next,
            )
            self.database.add_automation_event(
                automation_id=automation_id,
                event_type="run_error",
                message=f"Automation failed to queue run: {error}",
            )
            self._emit(
                "automation_run_error",
                {
                    "automation_id": automation_id,
                    "source": source,
                    "error": error,
                },
            )
            raise

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.telemetry is None:
            return
        try:
            self.telemetry.emit(event_type, payload)
        except Exception:
            self.logger.debug("automation_telemetry_emit_failed event=%s", event_type)

