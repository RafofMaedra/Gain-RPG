from __future__ import annotations

import argparse

from app.db import (
    get_notification_summary,
    get_player,
    mark_reminder_sent,
    should_send_evening_nudge,
    today_key,
    was_reminder_sent,
)
from app.notifier import DiscordNotifier, NoopNotifier, NtfyNotifier


def _build_notifier():
    player = get_player()
    if player.get("discord_webhook_url"):
        return DiscordNotifier(player["discord_webhook_url"])
    if player.get("ntfy_topic_url"):
        return NtfyNotifier(player["ntfy_topic_url"])
    return NoopNotifier()


def send_morning(for_date: str | None = None) -> bool:
    for_date = for_date or today_key()
    if was_reminder_sent("morning", for_date):
        return False
    summary = get_notification_summary(for_date)
    _build_notifier().send("Morning Rally", f"Minimum set keeps your Grit alive. Tonight: {summary['threat']}.")
    mark_reminder_sent("morning", for_date)
    return True


def send_evening(for_date: str | None = None) -> bool:
    for_date = for_date or today_key()
    if was_reminder_sent("evening", for_date):
        return False
    if not should_send_evening_nudge(for_date):
        return False
    _build_notifier().send("Evening Nudge", "You have not logged minimum set yet. Lock in before midnight.", priority="high")
    mark_reminder_sent("evening", for_date)
    return True


def send_midnight(for_date: str | None = None) -> bool:
    for_date = for_date or today_key()
    if was_reminder_sent("midnight", for_date):
        return False
    summary = get_notification_summary(for_date)
    body = f"Threat: {summary['threat']}."
    if summary["resolved"]:
        body += f" Latest result: {summary['result']}."
    _build_notifier().send("Midnight Summary", body)
    mark_reminder_sent("midnight", for_date)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["morning", "evening", "midnight"])
    args = parser.parse_args()

    if args.mode == "morning":
        send_morning()
    elif args.mode == "evening":
        send_evening()
    else:
        send_midnight()


if __name__ == "__main__":
    main()
