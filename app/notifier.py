from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class Notifier:
    def send(self, title: str, body: str, priority: str = "normal") -> None:
        raise NotImplementedError


class NoopNotifier(Notifier):
    def send(self, title: str, body: str, priority: str = "normal") -> None:
        return


class _HttpNotifier(Notifier):
    max_attempts = 3
    timeout_s = 5

    def _send_with_retry(self, req: urllib.request.Request) -> None:
        for attempt in range(1, self.max_attempts + 1):
            try:
                urllib.request.urlopen(req, timeout=self.timeout_s).read()
                return
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt >= self.max_attempts:
                    logger.warning("Notifier send failed after retries: %s", exc)
                    return
                time.sleep(0.25 * attempt)


class DiscordNotifier(_HttpNotifier):
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
        self._send_with_retry(req)


class NtfyNotifier(_HttpNotifier):
    def __init__(self, topic_url: str) -> None:
        self.topic_url = topic_url

    def send(self, title: str, body: str, priority: str = "normal") -> None:
        req = urllib.request.Request(
            self.topic_url,
            data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "3" if priority == "normal" else "4"},
            method="POST",
        )
        self._send_with_retry(req)
