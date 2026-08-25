"""SMS alerting via Twilio.

Alert payload is deliberately minimal per the build spec: ticker and price
at trigger time only, nothing else -- glanceable and actionable, not a data
dump. Gated behind both `live_alerting_enabled` (the diagnostic-first
rollout switch, see README) and `dry_run`; when either blocks sending, the
alert is logged instead so Phase-1 diagnostics still show what *would*
have fired.

A per-ticker cooldown avoids re-texting the same name every time it
reconfirms while a move is still running.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .config import Settings
from .storage import Storage

log = logging.getLogger(__name__)


class TwilioAlerter:
    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage
        self._client = None

        self.enabled = bool(
            settings.live_alerting_enabled
            and not settings.dry_run
            and settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_from_number
            and settings.twilio_to_numbers
        )
        if self.enabled:
            from twilio.rest import Client  # local import: optional dependency

            self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

    def cooldown_elapsed(self, ticker: str, now: datetime) -> bool:
        last = self.storage.last_alert_time(ticker)
        if last is None:
            return True
        return now - last >= timedelta(minutes=self.settings.alert_cooldown_minutes)

    @staticmethod
    def _format_message(ticker: str, price: float) -> str:
        return f"{ticker} ${price:.2f}"

    def send(self, ticker: str, price: float) -> bool:
        """Returns True if an SMS was actually sent (not just logged)."""
        message = self._format_message(ticker, price)

        if not self.enabled:
            log.info("[not sent -- live_alerting_enabled=%s dry_run=%s] %s",
                      self.settings.live_alerting_enabled, self.settings.dry_run, message)
            return False

        for to_number in self.settings.twilio_to_numbers:
            self._client.messages.create(
                body=message,
                from_=self.settings.twilio_from_number,
                to=to_number,
            )
        log.info("Sent SMS alert for %s to %d recipient(s)", ticker, len(self.settings.twilio_to_numbers))
        return True
