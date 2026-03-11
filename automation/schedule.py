from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

WEEKDAY_CODES: tuple[str, ...] = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
WEEKDAY_TO_INT: dict[str, int] = {code: index for index, code in enumerate(WEEKDAY_CODES)}


def validate_timezone(timezone_name: str | None) -> str:
    value = (timezone_name or "UTC").strip() or "UTC"
    try:
        ZoneInfo(value)
    except Exception as exc:
        raise ValueError(f"Invalid timezone: {value}") from exc
    return value


def normalize_schedule(
    *,
    schedule_type: str | None,
    schedule: dict[str, Any] | None,
    interval_sec: int | None = None,
) -> tuple[str, dict[str, Any], int]:
    normalized_type = (schedule_type or "interval").strip().lower() or "interval"
    payload = dict(schedule or {})

    if normalized_type == "interval":
        raw = payload.get("interval_sec", interval_sec if interval_sec is not None else 300)
        try:
            seconds = int(raw)
        except Exception as exc:
            raise ValueError("interval schedule requires integer interval_sec") from exc
        if seconds < 10:
            raise ValueError("interval_sec must be >= 10")
        return "interval", {"interval_sec": seconds}, seconds

    if normalized_type == "hourly":
        raw_hours = payload.get("interval_hours", 1)
        raw_minute = payload.get("minute", 0)
        try:
            interval_hours = int(raw_hours)
            minute = int(raw_minute)
        except Exception as exc:
            raise ValueError("hourly schedule requires integer interval_hours and minute") from exc
        if interval_hours < 1 or interval_hours > 24:
            raise ValueError("interval_hours must be in [1, 24]")
        if minute < 0 or minute > 59:
            raise ValueError("minute must be in [0, 59]")
        return "hourly", {"interval_hours": interval_hours, "minute": minute}, interval_hours * 3600

    if normalized_type == "weekly":
        byday_raw = payload.get("byday", ["MO"])
        hour_raw = payload.get("hour", 9)
        minute_raw = payload.get("minute", 0)

        if isinstance(byday_raw, str):
            byday_items = [item.strip().upper() for item in byday_raw.split(",") if item.strip()]
        elif isinstance(byday_raw, list):
            byday_items = [str(item).strip().upper() for item in byday_raw if str(item).strip()]
        else:
            raise ValueError("weekly schedule requires byday as list or comma-separated string")

        if not byday_items:
            raise ValueError("weekly schedule requires at least one day in byday")
        invalid_days = [item for item in byday_items if item not in WEEKDAY_TO_INT]
        if invalid_days:
            raise ValueError(f"Invalid byday values: {', '.join(invalid_days)}")

        dedup_days = sorted(set(byday_items), key=lambda item: WEEKDAY_TO_INT[item])

        try:
            hour = int(hour_raw)
            minute = int(minute_raw)
        except Exception as exc:
            raise ValueError("weekly schedule requires integer hour and minute") from exc
        if hour < 0 or hour > 23:
            raise ValueError("hour must be in [0, 23]")
        if minute < 0 or minute > 59:
            raise ValueError("minute must be in [0, 59]")

        return "weekly", {"byday": dedup_days, "hour": hour, "minute": minute}, 7 * 24 * 3600

    if normalized_type == "watch_fs":
        raw_path = str(payload.get("path", "")).strip()
        if not raw_path:
            raise ValueError("watch_fs schedule requires non-empty path")

        raw_poll = payload.get("poll_sec", interval_sec if interval_sec is not None else 10)
        try:
            poll_sec = int(raw_poll)
        except Exception as exc:
            raise ValueError("watch_fs schedule requires integer poll_sec") from exc
        if poll_sec < 2 or poll_sec > 3600:
            raise ValueError("poll_sec must be in [2, 3600]")

        raw_max = payload.get("max_changed_files", 20)
        try:
            max_changed_files = int(raw_max)
        except Exception as exc:
            raise ValueError("watch_fs schedule requires integer max_changed_files") from exc
        if max_changed_files < 1 or max_changed_files > 500:
            raise ValueError("max_changed_files must be in [1, 500]")

        state_raw = payload.get("last_seen_mtime_ns", 0)
        try:
            last_seen_mtime_ns = max(0, int(state_raw))
        except Exception:
            last_seen_mtime_ns = 0

        return (
            "watch_fs",
            {
                "path": raw_path,
                "poll_sec": poll_sec,
                "recursive": _to_bool(payload.get("recursive", True), default=True),
                "glob": str(payload.get("glob", "*")).strip() or "*",
                "max_changed_files": max_changed_files,
                "last_seen_mtime_ns": last_seen_mtime_ns,
            },
            poll_sec,
        )

    raise ValueError("Unsupported schedule_type. Allowed: interval, hourly, weekly, watch_fs")


def compute_next_run_at(
    *,
    schedule_type: str,
    schedule: dict[str, Any],
    timezone_name: str,
    now_utc: datetime | None = None,
) -> str:
    tz_name = validate_timezone(timezone_name)
    tz = ZoneInfo(tz_name)
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    if schedule_type == "interval":
        interval_sec = int(schedule.get("interval_sec", 300))
        next_utc = now + timedelta(seconds=max(10, interval_sec))
        return next_utc.isoformat()

    if schedule_type == "watch_fs":
        poll_sec = int(schedule.get("poll_sec", 10))
        next_utc = now + timedelta(seconds=max(2, poll_sec))
        return next_utc.isoformat()

    local_now = now.astimezone(tz)

    if schedule_type == "hourly":
        interval_hours = int(schedule.get("interval_hours", 1))
        minute = int(schedule.get("minute", 0))
        candidate = local_now.replace(second=0, microsecond=0, minute=minute)
        if candidate <= local_now:
            candidate += timedelta(hours=1)
            candidate = candidate.replace(minute=minute, second=0, microsecond=0)
        while candidate.hour % interval_hours != 0:
            candidate += timedelta(hours=1)
            candidate = candidate.replace(minute=minute, second=0, microsecond=0)
        return candidate.astimezone(timezone.utc).isoformat()

    if schedule_type == "weekly":
        byday = [str(item).upper() for item in schedule.get("byday", [])]
        hour = int(schedule.get("hour", 9))
        minute = int(schedule.get("minute", 0))
        weekdays = {WEEKDAY_TO_INT[item] for item in byday if item in WEEKDAY_TO_INT}
        if not weekdays:
            weekdays = {0}

        for offset in range(0, 15):
            date_candidate = (local_now + timedelta(days=offset)).date()
            weekday = date_candidate.weekday()
            if weekday not in weekdays:
                continue
            local_candidate = datetime.combine(
                date_candidate,
                time(hour=hour, minute=minute),
                tzinfo=tz,
            )
            if local_candidate <= local_now:
                continue
            return local_candidate.astimezone(timezone.utc).isoformat()

        fallback = (local_now + timedelta(days=7)).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        return fallback.astimezone(timezone.utc).isoformat()

    raise ValueError(f"Unsupported schedule_type: {schedule_type}")


def _to_bool(value: Any, default: bool) -> bool:
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
