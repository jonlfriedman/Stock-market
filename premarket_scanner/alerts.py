"""Push alerting via Pushover, with a per-ticker cooldown to avoid spamming
the same name every minute while it stays above threshold.

Pushover instead of SMS: a single HTTPS POST, no per-message carrier cost,
and delivery straight to the Pushover iOS/Android app -- no telco
registration step (Twilio's SMS senders require A2P 10DLC / toll-free
verification, which is friction for a single-user personal alert feed).

If Pushover isn't configured (or dry_run is set), alerts are logged instead
of sent -- useful for Phase-1 testing before credentials are wired up.
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
            not settings.dry_run and settings.pushover_api_token and settings.pushover_user_key
        )

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
            f"[{phase}]\n"
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
        title = f"{ticker} score {score:.2f}"

        if not self.enabled:
            log.info("[DRY RUN, alert not sent] %s | %s", title, message.replace("\n", " | "))
            return

        resp = requests.post(
            PUSHOVER_API_URL,
            data={
                "token": self.settings.pushover_api_token,
                "user": self.settings.pushover_user_key,
                "title": title,
                "message": message,
                "priority": self.settings.pushover_priority,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            log.error("Pushover alert failed for %s: HTTP %s %s", ticker, resp.status_code, resp.text)
            return
        log.info("Sent Pushover alert for %s", ticker)
