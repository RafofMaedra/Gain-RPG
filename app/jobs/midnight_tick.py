from __future__ import annotations

from app.db import get_notification_summary, get_player, run_midnight_tick
from app.notifier import DiscordNotifier, NoopNotifier, NtfyNotifier


def _build_notifier():
    player = get_player()
    if player.get("discord_webhook_url"):
        return DiscordNotifier(player["discord_webhook_url"])
    if player.get("ntfy_topic_url"):
        return NtfyNotifier(player["ntfy_topic_url"])
    return NoopNotifier()


def main() -> None:
    result = run_midnight_tick()
    summary = get_notification_summary(result["today"])
    _build_notifier().send(
        "Gain RPG Midnight Tick",
        f"Prepared {result['today']}. Yesterday auto-resolved: {result['resolved_yesterday']}. Tonight threat: {summary['threat']}.",
    )


if __name__ == "__main__":
    main()
