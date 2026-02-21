from __future__ import annotations

import unittest
from unittest.mock import patch

from app.jobs.schedule_runner import main


class ScheduleRunnerTests(unittest.TestCase):
    @patch("app.jobs.schedule_runner.send_evening")
    @patch("app.jobs.schedule_runner.send_morning")
    @patch("app.jobs.schedule_runner.send_midnight")
    @patch("app.jobs.schedule_runner.run_midnight_tick")
    @patch("app.jobs.schedule_runner.get_schedule_context")
    def test_midnight_window_triggers_tick_and_midnight(
        self,
        get_schedule_context,
        run_midnight_tick,
        send_midnight,
        send_morning,
        send_evening,
    ) -> None:
        get_schedule_context.return_value = {
            "local_date": "2026-02-21",
            "local_hour": 0,
            "local_minute": 5,
            "timezone": "Pacific/Auckland",
        }

        main()

        run_midnight_tick.assert_called_once()
        send_midnight.assert_called_once_with("2026-02-21")
        send_morning.assert_not_called()
        send_evening.assert_not_called()


if __name__ == "__main__":
    unittest.main()
