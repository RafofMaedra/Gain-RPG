from __future__ import annotations

import argparse

from app.db import get_notification_summary, get_player, should_send_evening_nudge, today_key
from app.notifier import DiscordNotifier, NoopNotifier, NtfyNotifier


def _build_notifier():
    player = get_player()
    if player.get("discord_webhook_url"):
        return DiscordNotifier(player["discord_webhook_url"])
    if player.get("ntfy_topic_url"):
        return NtfyNotifier(player["ntfy_topic_url"])
    return NoopNotifier()


def send_morning() -> None:
    summary = get_notification_summary(today_key())
    _build_notifier().send("Morning Rally", f"Minimum set keeps your Grit alive. Tonight: {summary['threat']}.")


def send_evening() -> None:
    today = today_key()
    if should_send_evening_nudge(today):
        _build_notifier().send("Evening Nudge", "You have not logged minimum set yet. Lock in before midnight.", priority="high")


def send_midnight() -> None:
    summary = get_notification_summary(today_key())
    body = f"Threat: {summary['threat']}."
    if summary["resolved"]:
        body += f" Latest result: {summary['result']}."
    _build_notifier().send("Midnight Summary", body)


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
