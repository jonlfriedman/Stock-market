"""Push alerting via Pushover.

Pushover instead of SMS: a single HTTPS POST, no per-message carrier cost,
delivery straight to the Pushover iOS/Android app, and no telco
registration step (Twilio's SMS senders require A2P 10DLC / toll-free
verification, which is friction for a single-user personal alert feed).

Alert payload is deliberately minimal per the build spec: ticker and price
at trigger time only, nothing else -- glanceable and actionable, not a data
dump. Gated behind both `live_alerting_enabled` (the diagnostic-first
rollout switch, see README) and `dry_run`; when either blocks sending, the
alert is logged instead so Phase-1 diagnostics still show what *would*
have fired.

A per-ticker cooldown avoids re-pushing the same name every time it
reconfirms while a move is still running.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

from .config import Settings
from .storage import Storage

log = logging.getLogger(__name__)

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
REQUEST_TIMEOUT_SECONDS = 15


class PushoverAlerter:
    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage

        self.enabled = bool(
            settings.live_alerting_enabled
            and not settings.dry_run
            and settings.pushover_api_token
            and settings.pushover_user_key
        )

    def cooldown_elapsed(self, ticker: str, now: datetime) -> bool:
        last = self.storage.last_alert_time(ticker)
        if last is None:
            return True
        return now - last >= timedelta(minutes=self.settings.alert_cooldown_minutes)

    @staticmethod
    def _format_message(ticker: str, price: float) -> str:
        return f"{ticker} ${price:.2f}"

    def send(self, ticker: str, price: float) -> bool:
        """Returns True if a push was actually sent (not just logged)."""
        message = self._format_message(ticker, price)

        if not self.enabled:
            log.info("[not sent -- live_alerting_enabled=%s dry_run=%s] %s",
                      self.settings.live_alerting_enabled, self.settings.dry_run, message)
            return False

        resp = requests.post(
            PUSHOVER_API_URL,
            data={
                "token": self.settings.pushover_api_token,
                "user": self.settings.pushover_user_key,
                "message": message,
                "priority": self.settings.pushover_priority,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            log.error("Pushover alert failed for %s: HTTP %s %s", ticker, resp.status_code, resp.text)
            return False

        log.info("Sent Pushover alert for %s", ticker)
        return True
