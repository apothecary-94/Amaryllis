from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
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
        escalation_warning_threshold: int = 2,
        escalation_critical_threshold: int = 4,
        escalation_disable_threshold: int = 6,
        telemetry: TelemetrySink | None = None,
    ) -> None:
        self.logger = logging.getLogger("amaryllis.automation.scheduler")
        self.database = database
        self.run_manager = run_manager
        self.poll_interval_sec = max(0.5, float(poll_interval_sec))
        self.batch_size = max(1, int(batch_size))
        self.escalation_warning_threshold = max(1, int(escalation_warning_threshold))
        self.escalation_critical_threshold = max(
            self.escalation_warning_threshold,
            int(escalation_critical_threshold),
        )
        self.escalation_disable_threshold = max(
            self.escalation_critical_threshold + 1,
            int(escalation_disable_threshold),
        )
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
            (
                "automation_scheduler_started poll_interval_sec=%s batch_size=%s "
                "escalation_warning=%s escalation_critical=%s escalation_disable=%s"
            ),
            self.poll_interval_sec,
            self.batch_size,
            self.escalation_warning_threshold,
            self.escalation_critical_threshold,
            self.escalation_disable_threshold,
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
        raw_schedule = schedule if isinstance(schedule, dict) else {}
        normalized_type, normalized_schedule, normalized_interval = normalize_schedule(
            schedule_type=schedule_type,
            schedule=schedule,
            interval_sec=interval_sec,
        )
        if normalized_type == "watch_fs" and "last_seen_mtime_ns" not in raw_schedule:
            normalized_schedule["last_seen_mtime_ns"] = self._current_watch_cursor(normalized_schedule)
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
        provided_schedule = schedule if isinstance(schedule, dict) else None

        normalized_type, normalized_schedule, normalized_interval = normalize_schedule(
            schedule_type=schedule_type or current_type,
            schedule=schedule if schedule is not None else current_schedule,
            interval_sec=interval_sec if interval_sec is not None else current_interval,
        )
        if normalized_type == "watch_fs" and provided_schedule is not None and "last_seen_mtime_ns" not in provided_schedule:
            normalized_schedule["last_seen_mtime_ns"] = self._current_watch_cursor(normalized_schedule)
        normalized_timezone = validate_timezone(timezone_name or str(automation.get("timezone", "UTC")))

        updates: dict[str, Any] = {
            "interval_sec": normalized_interval,
            "schedule_type": normalized_type,
            "schedule_json": normalized_schedule,
            "timezone": normalized_timezone,
            "last_error": None,
            "consecutive_failures": 0,
            "escalation_level": "none",
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
            consecutive_failures=0,
            escalation_level="none",
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

    def list_inbox_items(
        self,
        *,
        user_id: str | None = None,
        unread_only: bool = False,
        category: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self.database.list_inbox_items(
            user_id=user_id,
            unread_only=unread_only,
            category=category,
            limit=limit,
        )

    def set_inbox_item_read(self, item_id: str, is_read: bool) -> dict[str, Any]:
        item = self.database.set_inbox_item_read(item_id=item_id, is_read=is_read)
        if item is None:
            raise ValueError(f"Inbox item not found: {item_id}")
        return item

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
        user_id = str(automation["user_id"])
        previous_failures = max(0, int(automation.get("consecutive_failures", 0)))
        previous_level = str(automation.get("escalation_level", "none")).strip().lower() or "none"

        next_run_at = compute_next_run_at(
            schedule_type=schedule_type,
            schedule=schedule,
            timezone_name=timezone_name,
            now_utc=now,
        )

        try:
            run_message = str(automation["message"])
            changed_files: list[str] = []
            if schedule_type == "watch_fs":
                changed_files, schedule = self._scan_watch_changes(schedule)
                if source != "manual" and not changed_files:
                    self.database.update_automation_fields(
                        automation_id,
                        next_run_at=next_run_at,
                        interval_sec=interval_sec,
                        schedule_type=schedule_type,
                        schedule_json=schedule,
                        timezone=timezone_name,
                    )
                    self._emit(
                        "automation_watch_idle",
                        {
                            "automation_id": automation_id,
                            "source": source,
                        },
                    )
                    return
                if changed_files:
                    run_message = self._build_watch_message(
                        base_message=run_message,
                        changed_files=changed_files,
                    )

            agent_record = self.database.get_agent(str(automation["agent_id"]))
            if agent_record is None:
                raise ValueError(f"Agent not found: {automation['agent_id']}")

            run = self.run_manager.create_run(
                agent=Agent.from_record(agent_record),
                user_id=user_id,
                session_id=automation.get("session_id"),
                user_message=run_message,
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
                consecutive_failures=0,
                escalation_level="none",
            )
            if previous_failures > 0 or previous_level != "none":
                self.database.add_automation_event(
                    automation_id=automation_id,
                    event_type="recovered",
                    message="Automation recovered after previous failures.",
                    run_id=run_id,
                )
                self._notify_recovered(
                    automation_id=automation_id,
                    user_id=user_id,
                    previous_failures=previous_failures,
                )

            self.database.add_automation_event(
                automation_id=automation_id,
                event_type="run_queued",
                message=(
                    f"Automation queued run ({source})"
                    if not changed_files
                    else (
                        f"Automation queued run ({source}); "
                        f"watcher detected {len(changed_files)} changed files."
                    )
                ),
                run_id=run_id,
            )
            if changed_files and source != "manual":
                self._notify_watch_triggered(
                    automation_id=automation_id,
                    user_id=user_id,
                    changed_files=changed_files,
                    watch_path=str(schedule.get("path", "")),
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
            failures = previous_failures + 1
            level = self._escalation_level_for_failures(failures)
            disable_now = failures >= self.escalation_disable_threshold
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
                interval_sec=interval_sec,
                schedule_type=schedule_type,
                schedule_json=schedule,
                timezone=timezone_name,
                consecutive_failures=failures,
                escalation_level=level,
                is_enabled=False if disable_now else bool(automation.get("is_enabled", True)),
            )
            self.database.add_automation_event(
                automation_id=automation_id,
                event_type="run_error",
                message=(
                    f"Automation failed to queue run: {error} "
                    f"(consecutive_failures={failures}, escalation={level})"
                ),
            )
            should_notify_escalation = (level != previous_level and level != "none") or (
                disable_now and bool(automation.get("is_enabled", True))
            )
            if should_notify_escalation:
                self._notify_escalation(
                    automation_id=automation_id,
                    user_id=user_id,
                    error=error,
                    failures=failures,
                    level=level,
                    disabled=disable_now,
                )
            self._emit(
                "automation_run_error",
                {
                    "automation_id": automation_id,
                    "source": source,
                    "error": error,
                    "consecutive_failures": failures,
                    "escalation_level": level,
                    "disabled": disable_now,
                },
            )
            raise

    @staticmethod
    def _build_watch_message(base_message: str, changed_files: list[str]) -> str:
        lines = [base_message.strip(), "", "Watcher detected file changes:"]
        for item in changed_files:
            lines.append(f"- {item}")
        return "\n".join(lines).strip()

    @staticmethod
    def _parse_bool(value: Any, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default

    def _current_watch_cursor(self, schedule: dict[str, Any]) -> int:
        _, updated = self._scan_watch_changes(schedule)
        try:
            return max(0, int(updated.get("last_seen_mtime_ns", 0)))
        except Exception:
            return 0

    def _scan_watch_changes(self, schedule: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        watch_path_raw = str(schedule.get("path", "")).strip()
        if not watch_path_raw:
            raise ValueError("watch_fs schedule requires path")

        watch_path = Path(watch_path_raw).expanduser()
        if not watch_path.exists():
            raise ValueError(f"watch_fs path does not exist: {watch_path}")

        recursive = self._parse_bool(schedule.get("recursive", True), default=True)
        pattern = str(schedule.get("glob", "*")).strip() or "*"
        max_changed_files = max(1, int(schedule.get("max_changed_files", 20)))
        last_seen_mtime_ns = max(0, int(schedule.get("last_seen_mtime_ns", 0)))

        candidates: list[Path]
        if watch_path.is_file():
            candidates = [watch_path]
        else:
            if recursive:
                candidates = [item for item in watch_path.rglob(pattern)]
            else:
                candidates = [item for item in watch_path.glob(pattern)]

        changed_rows: list[tuple[int, str]] = []
        max_seen = last_seen_mtime_ns
        for item in candidates:
            try:
                if not item.is_file():
                    continue
                stat = item.stat()
            except OSError:
                continue

            mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
            if mtime_ns > max_seen:
                max_seen = mtime_ns
            if mtime_ns <= last_seen_mtime_ns:
                continue

            if watch_path.is_dir():
                try:
                    display = str(item.relative_to(watch_path))
                except Exception:
                    display = str(item)
            else:
                display = item.name
            changed_rows.append((mtime_ns, display))

        changed_rows.sort(key=lambda row: row[0])
        changed_files = [row[1] for row in changed_rows[-max_changed_files:]]
        updated_schedule = dict(schedule)
        updated_schedule["path"] = str(watch_path)
        updated_schedule["poll_sec"] = max(2, int(schedule.get("poll_sec", 10)))
        updated_schedule["recursive"] = recursive
        updated_schedule["glob"] = pattern
        updated_schedule["max_changed_files"] = max_changed_files
        updated_schedule["last_seen_mtime_ns"] = max_seen
        return changed_files, updated_schedule

    def _escalation_level_for_failures(self, failures: int) -> str:
        if failures >= self.escalation_critical_threshold:
            return "critical"
        if failures >= self.escalation_warning_threshold:
            return "warning"
        return "none"

    def _notify_watch_triggered(
        self,
        *,
        automation_id: str,
        user_id: str,
        changed_files: list[str],
        watch_path: str,
        run_id: str,
    ) -> None:
        title = "Automation watcher triggered"
        preview = ", ".join(changed_files[:3])
        if len(changed_files) > 3:
            preview = f"{preview}, +{len(changed_files) - 3} more"
        body = (
            f"Automation {automation_id} queued a run because files changed in {watch_path}. "
            f"Changed: {preview}."
        )
        self.database.add_inbox_item(
            user_id=user_id,
            category="automation",
            severity="info",
            title=title,
            body=body,
            source_type="automation",
            source_id=automation_id,
            run_id=run_id,
            metadata={
                "changed_files": changed_files,
                "watch_path": watch_path,
            },
            requires_action=False,
        )

    def _notify_escalation(
        self,
        *,
        automation_id: str,
        user_id: str,
        error: str,
        failures: int,
        level: str,
        disabled: bool,
    ) -> None:
        if disabled:
            title = "Automation disabled after failures"
            severity = "error"
            requires_action = True
            body = (
                f"Automation {automation_id} was disabled after {failures} consecutive failures. "
                f"Latest error: {error}"
            )
        elif level == "critical":
            title = "Automation in critical failure state"
            severity = "error"
            requires_action = True
            body = (
                f"Automation {automation_id} reached critical escalation "
                f"({failures} consecutive failures). Latest error: {error}"
            )
        else:
            title = "Automation warning"
            severity = "warning"
            requires_action = False
            body = (
                f"Automation {automation_id} has {failures} consecutive failures. "
                f"Latest error: {error}"
            )

        self.database.add_inbox_item(
            user_id=user_id,
            category="automation",
            severity=severity,
            title=title,
            body=body,
            source_type="automation",
            source_id=automation_id,
            metadata={
                "consecutive_failures": failures,
                "escalation_level": level,
                "disabled": disabled,
            },
            requires_action=requires_action,
        )

    def _notify_recovered(self, *, automation_id: str, user_id: str, previous_failures: int) -> None:
        self.database.add_inbox_item(
            user_id=user_id,
            category="automation",
            severity="info",
            title="Automation recovered",
            body=(
                f"Automation {automation_id} recovered and resumed normal operation "
                f"after {previous_failures} consecutive failures."
            ),
            source_type="automation",
            source_id=automation_id,
            metadata={
                "previous_failures": previous_failures,
                "status": "recovered",
            },
            requires_action=False,
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.telemetry is None:
            return
        try:
            self.telemetry.emit(event_type, payload)
        except Exception:
            self.logger.debug("automation_telemetry_emit_failed event=%s", event_type)
