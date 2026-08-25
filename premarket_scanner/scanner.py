"""Main polling loop.

Runs continuously (intended to be managed by systemd -- see deploy/).
Active window per weekday: `universe_fetch_time` (universe screen must
complete before the baseline window) through `scan_end_time` (end of
effectiveness tracking). Sleeps between windows otherwise, so it's safe to
leave running continuously.

Every poll during the baseline and trigger phases is logged to a per-day
CSV in data/logs/, regardless of whether it crosses a trigger -- that raw
log is what the diagnostic-first rollout (see README) is analyzed from.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import finviz_client, universe
from .alerts import TwilioAlerter
from .config import Settings, load_settings
from .effectiveness import EffectivenessTracker
from .storage import Storage
from .trigger import TriggerEngine

log = logging.getLogger(__name__)


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _time_of(now: datetime, hhmm: str) -> datetime:
    hour, minute = _parse_hhmm(hhmm)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def within_scan_window(now: datetime, settings: Settings) -> bool:
    if now.weekday() >= 5:  # Sat/Sun
        return False
    start = _time_of(now, settings.universe_fetch_time)
    end = _time_of(now, settings.scan_end_time)
    return start <= now <= end


def seconds_until_next_window(now: datetime, settings: Settings) -> float:
    start_h, start_m = _parse_hhmm(settings.universe_fetch_time)
    candidate = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return (candidate - now).total_seconds()


def current_phase(now: datetime, settings: Settings) -> str:
    """One of 'pre_baseline', 'baseline', 'trigger', 'outside'."""
    if not within_scan_window(now, settings):
        return "outside"
    baseline_start = _time_of(now, settings.baseline_start_time)
    trigger_start = _time_of(now, settings.trigger_start_time)
    if now < baseline_start:
        return "pre_baseline"
    if now < trigger_start:
        return "baseline"
    return "trigger"


class ScanState:
    """Per-day state that must survive across poll cycles within one session."""

    def __init__(self) -> None:
        self.trade_date: str | None = None
        self.tickers: list[str] = []
        self.baseline_finalized = False
        self.engine: TriggerEngine | None = None

    def reset_for_new_day(self, trade_date: str, engine: TriggerEngine) -> None:
        self.trade_date = trade_date
        self.tickers = []
        self.baseline_finalized = False
        self.engine = engine


def poll_once(
    settings: Settings,
    storage: Storage,
    state: ScanState,
    alerter: TwilioAlerter,
    effectiveness: EffectivenessTracker,
    now: datetime,
) -> None:
    trade_date = now.date().isoformat()
    if state.trade_date != trade_date:
        state.reset_for_new_day(trade_date, TriggerEngine(settings.trigger_multiplier, settings.confirmation_minutes))

    phase = current_phase(now, settings)

    if phase == "outside":
        return

    if not state.tickers:
        state.tickers = universe.get_universe(settings, now)
        log.info("Session universe: %d tickers", len(state.tickers))

    if phase == "pre_baseline":
        return  # universe fetched/cached; nothing to poll yet

    if not state.tickers:
        log.warning("No tickers in universe; skipping poll at %s", now.isoformat())
        return

    assert state.engine is not None
    snapshots = finviz_client.fetch_quotes(settings, state.tickers, now)
    log.info("Polled %d/%d tickers at %s (phase=%s)", len(snapshots), len(state.tickers), now.isoformat(), phase)
    prices = {snap.ticker: snap.price for snap in snapshots}

    if phase == "trigger" and not state.baseline_finalized:
        state.engine.finalize_baseline()
        state.baseline_finalized = True
        log.info("Baseline finalized for %d tickers", len(state.tickers))

    for snap in snapshots:
        if phase == "baseline":
            state.engine.record_baseline_reading(snap.ticker, snap.volume)
            storage.append_scan_log(
                trade_date,
                {
                    "timestamp": now.isoformat(),
                    "phase": "baseline",
                    "ticker": snap.ticker,
                    "price": snap.price,
                    "cumulative_volume": snap.volume,
                    "minute_volume": "",
                    "baseline_avg_vol_per_min": "",
                    "ratio_to_baseline": "",
                    "trigger1_fired": False,
                    "trigger2_confirmed": False,
                    "alerted": False,
                },
            )
            continue

        # phase == "trigger"
        reading = state.engine.evaluate(snap.ticker, now, snap.volume)
        alerted = False

        if reading.trigger2_confirmed:
            sent = False
            if alerter.cooldown_elapsed(snap.ticker, now):
                sent = alerter.send(snap.ticker, snap.price)
            storage.record_confirmed_trigger(
                snap.ticker,
                now,
                snap.price,
                reading.baseline_avg or 0.0,
                reading.minute_volume or 0.0,
                alerted=sent,
            )
            effectiveness.schedule(snap.ticker, now, snap.price)
            alerted = sent

        storage.append_scan_log(
            trade_date,
            {
                "timestamp": now.isoformat(),
                "phase": "trigger",
                "ticker": snap.ticker,
                "price": snap.price,
                "cumulative_volume": snap.volume,
                "minute_volume": reading.minute_volume if reading.minute_volume is not None else "",
                "baseline_avg_vol_per_min": reading.baseline_avg if reading.baseline_avg is not None else "",
                "ratio_to_baseline": round(reading.ratio_to_baseline, 4) if reading.ratio_to_baseline is not None else "",
                "trigger1_fired": reading.trigger1_fired,
                "trigger2_confirmed": reading.trigger2_confirmed,
                "alerted": alerted,
            },
        )

    effectiveness.process_due(now, prices)


def run(settings: Settings, once: bool = False) -> None:
    tz = ZoneInfo(settings.timezone)
    storage = Storage(settings.data_dir)
    alerter = TwilioAlerter(settings, storage)
    effectiveness = EffectivenessTracker(storage, settings)
    state = ScanState()

    if not settings.live_alerting_enabled:
        log.warning(
            "live_alerting_enabled=false -- running in diagnostic/log-only mode, "
            "no SMS will be sent regardless of Twilio config."
        )

    try:
        while True:
            now = datetime.now(tz)

            if not once and not within_scan_window(now, settings):
                sleep_s = min(seconds_until_next_window(now, settings), 3600)
                log.info("Outside scan window; sleeping %.0fs", sleep_s)
                time.sleep(sleep_s)
                continue

            cycle_start = time.monotonic()
            try:
                poll_once(settings, storage, state, alerter, effectiveness, now)
            except finviz_client.FinvizError as exc:
                log.error("Finviz fetch failed: %s", exc)
            except Exception:
                log.exception("Unexpected error during poll cycle")

            if once:
                break

            elapsed = time.monotonic() - cycle_start
            time.sleep(max(0.0, settings.poll_interval_seconds - elapsed))
    finally:
        storage.close()


def main(argv: list[str] | None = None) -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Premarket volume acceleration scanner")
    parser.add_argument("--profile", choices=["discovery", "watchlist"], default=None)
    parser.add_argument("--once", action="store_true", help="Run a single poll cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Never actually send SMS")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.profile:
        os.environ["SCANNER_PROFILE"] = args.profile

    settings = load_settings()
    if args.dry_run:
        settings.dry_run = True

    run(settings, once=args.once)


if __name__ == "__main__":
    main()
