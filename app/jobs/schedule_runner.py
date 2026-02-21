from __future__ import annotations

from app.db import get_schedule_context, run_midnight_tick
from app.jobs.reminders import send_evening, send_midnight, send_morning


def main() -> None:
    ctx = get_schedule_context()
    today = ctx["local_date"]
    hour = ctx["local_hour"]
    minute = ctx["local_minute"]

    # Run this command every 5-10 minutes via cron/systemd timer.
    if hour == 0 and minute < 15:
        run_midnight_tick()
        send_midnight(today)

    if hour == 8 and minute < 15:
        send_morning(today)

    if hour == 19 and minute < 15:
        send_evening(today)


if __name__ == "__main__":
    main()
