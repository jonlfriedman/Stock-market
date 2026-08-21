"""SMS alerting via Twilio, with a per-ticker cooldown to avoid spamming
the same name every minute while it stays above threshold.

If Twilio isn't configured (or dry_run is set), alerts are logged instead
of sent -- useful for Phase-1 testing before credentials are wired up.
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
            not settings.dry_run
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

    def _format_message(
        self,
        ticker: str,
        now: datetime,
        score: float,
        accel_ratios: list[float],
        rvol: float,
        rvol_source: str,
        price_change_pct: float,
        cumulative_volume: int,
    ) -> str:
        trading_hour, trading_minute = (int(x) for x in self.settings.trading_window_start.split(":"))
        trading_start = now.replace(hour=trading_hour, minute=trading_minute, second=0, microsecond=0)
        phase = "ACTIONABLE" if now >= trading_start else "awareness only, before trading window"
        ratios_str = "/".join(f"{r:.2f}x" for r in accel_ratios)
        return (
            f"{ticker} score {score:.2f} [{phase}]\n"
            f"accel ratios {ratios_str} | rvol {rvol:.2f}x ({rvol_source}) | "
            f"price {price_change_pct:+.2f}% | vol {cumulative_volume:,}\n"
            f"{now.strftime('%H:%M %Z')}"
        )

    def send(
        self,
        ticker: str,
        now: datetime,
        score: float,
        accel_ratios: list[float],
        rvol: float,
        rvol_source: str,
        price_change_pct: float,
        cumulative_volume: int,
    ) -> None:
        message = self._format_message(
            ticker, now, score, accel_ratios, rvol, rvol_source, price_change_pct, cumulative_volume
        )

        if not self.enabled:
            log.info("[DRY RUN, alert not sent] %s", message.replace("\n", " | "))
            return

        for to_number in self.settings.twilio_to_numbers:
            self._client.messages.create(
                body=message,
                from_=self.settings.twilio_from_number,
                to=to_number,
            )
        log.info("Sent SMS alert for %s to %d recipient(s)", ticker, len(self.settings.twilio_to_numbers))
