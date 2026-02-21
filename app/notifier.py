from __future__ import annotations

import json
import urllib.request


class Notifier:
    def send(self, title: str, body: str, priority: str = "normal") -> None:
        raise NotImplementedError


class NoopNotifier(Notifier):
    def send(self, title: str, body: str, priority: str = "normal") -> None:
        return


class DiscordNotifier(Notifier):
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, title: str, body: str, priority: str = "normal") -> None:
        payload = {"content": f"**{title}**\n{body}"}
        req = urllib.request.Request(
            self.webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()


class NtfyNotifier(Notifier):
    def __init__(self, topic_url: str) -> None:
        self.topic_url = topic_url

    def send(self, title: str, body: str, priority: str = "normal") -> None:
        req = urllib.request.Request(
            self.topic_url,
            data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "3" if priority == "normal" else "4"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
