"""Hermes-mediated notification delivery with durable retry semantics."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from brontes.ledger import Ledger


class HermesNotificationDispatcher:
    """Deliver persisted Brontes events to a local Hermes bridge endpoint."""

    def __init__(self, ledger: Ledger, notification_url: str, *, target_profile: str = "default") -> None:
        self._ledger = ledger
        self._notification_url = notification_url
        self._target_profile = target_profile

    def deliver_pending(self) -> int:
        delivered = 0
        for notification in self._ledger.pending_notifications():
            payload = json.dumps(
                {
                    "event_type": "brontes.roadtrip_charge_ready",
                    "target_profile": self._target_profile,
                    "text": notification.message,
                    "roadtrip_callback": notification.roadtrip_callback,
                    "session_id": notification.session_id,
                }
            ).encode("utf-8")
            request = Request(
                self._notification_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=10) as response:
                    if not 200 <= response.status < 300:
                        continue
            except (HTTPError, URLError, TimeoutError):
                continue
            self._ledger.mark_notification_delivered(
                notification.id, delivered_at=datetime.now(timezone.utc)
            )
            delivered += 1
        return delivered


class HermesCliNotificationDispatcher:
    """Deliver persisted notifications through the configured Hermes Telegram route."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        target: str = "telegram",
        run: Callable[[list[str]], str] | None = None,
    ) -> None:
        self._ledger = ledger
        self._target = target
        self._run = run or self._run_command

    def deliver_pending(self) -> int:
        delivered = 0
        for notification in self._ledger.pending_notifications():
            try:
                result = json.loads(
                    self._run(["hermes", "send", "--to", self._target, "--json", notification.message])
                )
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
                continue
            if not isinstance(result, dict) or result.get("success") is not True:
                continue
            self._ledger.mark_notification_delivered(
                notification.id, delivered_at=datetime.now(timezone.utc)
            )
            delivered += 1
        return delivered

    @staticmethod
    def _run_command(command: list[str]) -> str:
        result = subprocess.run(command, check=True, text=True, capture_output=True, timeout=30)
        return result.stdout
