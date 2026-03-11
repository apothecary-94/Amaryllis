from __future__ import annotations

import unittest
from datetime import datetime, timezone

from automation.schedule import compute_next_run_at, normalize_schedule


class AutomationScheduleTests(unittest.TestCase):
    def test_normalize_interval_schedule(self) -> None:
        schedule_type, payload, interval = normalize_schedule(
            schedule_type="interval",
            schedule={"interval_sec": 120},
            interval_sec=None,
        )
        self.assertEqual(schedule_type, "interval")
        self.assertEqual(payload["interval_sec"], 120)
        self.assertEqual(interval, 120)

    def test_compute_hourly_next_run(self) -> None:
        now = datetime(2026, 3, 11, 10, 20, tzinfo=timezone.utc)
        value = compute_next_run_at(
            schedule_type="hourly",
            schedule={"interval_hours": 3, "minute": 15},
            timezone_name="UTC",
            now_utc=now,
        )
        self.assertEqual(value, "2026-03-11T12:15:00+00:00")

    def test_compute_weekly_next_run(self) -> None:
        now = datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc)  # Wednesday
        value = compute_next_run_at(
            schedule_type="weekly",
            schedule={"byday": ["MO", "WE"], "hour": 9, "minute": 30},
            timezone_name="UTC",
            now_utc=now,
        )
        self.assertEqual(value, "2026-03-16T09:30:00+00:00")


if __name__ == "__main__":
    unittest.main()

