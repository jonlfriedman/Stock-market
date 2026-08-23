"""Main polling loop.

Runs continuously (intended to be managed by systemd -- see deploy/). Only
polls Finviz during the configured premarket scan window on weekdays;
sleeps between windows otherwise. Every poll cycle is logged to a per-day
CSV in data/logs/ regardless of whether it crosses the alert threshold, so
Phase-1 thresholds can be tuned from real observed data.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import finviz_client
from .alerts import PushoverAlerter
from .buffer import RollingBuffer
from .config import Settings, load_settings
from .rvol import RvolCalculator, time_bucket
from .scoring import compute_acceleration, compute_score
from .storage import Storage

log = logging.getLogger(__name__)


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.split(":")
    return int(hour), int(minute)


def within_scan_window(now: datetime, settings: Settings) -> bool:
    if now.weekday() >= 5:  # Sat/Sun
        return False
    start_h, start_m = _parse_hhmm(settings.scan_start_time)
    end_h, end_m = _parse_hhmm(settings.scan_end_time)
    start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    return start <= now <= end


def seconds_until_next_window(now: datetime, settings: Settings) -> float:
    start_h, start_m = _parse_hhmm(settings.scan_start_time)
    candidate = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return (candidate - now).total_seconds()


def poll_once(
    settings: Settings,
    storage: Storage,
    buffer: RollingBuffer,
    rvol_calc: RvolCalculator,
    alerter: PushoverAlerter,
    now: datetime,
) -> None:
    snapshots = finviz_client.fetch_snapshot(settings.finviz_export_url, settings.field_map, now)
    trade_date = now.date().isoformat()
    bucket = time_bucket(now, settings.rvol_time_bucket_minutes)

    log.info("Polled %d tickers from Finviz at %s", len(snapshots), now.isoformat())

    for snap in snapshots:
        buffer.update(snap.ticker, now, snap.volume, snap.price)
        storage.record_volume_snapshot(snap.ticker, trade_date, bucket, snap.volume, snap.price)

        row = {
            "timestamp": now.isoformat(),
            "ticker": snap.ticker,
            "price": snap.price,
            "cumulative_volume": snap.volume,
            "acceleration_score": 0.0,
            "sustained": False,
            "rvol": "",
            "rvol_source": "",
            "price_change_pct": "",
            "score": "",
            "alerted": False,
        }

        if not buffer.warmed_up(snap.ticker, settings.min_warmup_minutes):
            continue

        deltas = buffer.get_window_deltas(snap.ticker, settings.accel_windows)
        if deltas is None:
            continue

        accel = compute_acceleration(deltas)
        row["acceleration_score"] = round(accel.score, 4)
        row["sustained"] = accel.sustained

        rvol_result = rvol_calc.compute(snap.ticker, now, snap.volume, snap.rel_volume)
        price_change_pct = buffer.get_price_change_pct(snap.ticker)
        if price_change_pct is None:
            price_change_pct = snap.change_pct or 0.0

        row["rvol"] = round(rvol_result.value, 4) if rvol_result.value is not None else ""
        row["rvol_source"] = rvol_result.source
        row["price_change_pct"] = round(price_change_pct, 4)

        if not accel.sustained or rvol_result.value is None:
            storage.append_score_log(trade_date, row)
            continue

        score = compute_score(
            accel.score,
            rvol_result.value,
            abs(price_change_pct),
            settings.weight_acceleration,
            settings.weight_rvol,
            settings.weight_price,
        )
        row["score"] = round(score, 4)

        if score >= settings.score_threshold and alerter.cooldown_elapsed(snap.ticker, now):
            alerter.send(
                snap.ticker,
                now,
                score,
                accel.ratios,
                rvol_result.value,
                rvol_result.source,
                price_change_pct,
                snap.volume,
            )
            storage.record_alert(
                snap.ticker,
                now,
                score,
                accel.score,
                rvol_result.value,
                price_change_pct,
                snap.volume,
                snap.price,
            )
            row["alerted"] = True

        storage.append_score_log(trade_date, row)

    storage.backfill_alert_outcomes(now, settings.rvol_time_bucket_minutes)


def run(settings: Settings, once: bool = False) -> None:
    tz = ZoneInfo(settings.timezone)
    storage = Storage(settings.data_dir)
    buffer = RollingBuffer(settings.buffer_window_minutes, settings.poll_interval_seconds)
    rvol_calc = RvolCalculator(storage, settings)
    alerter = PushoverAlerter(settings, storage)

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
                poll_once(settings, storage, buffer, rvol_calc, alerter, now)
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

    import os

    if args.profile:
        os.environ["SCANNER_PROFILE"] = args.profile

    settings = load_settings()
    if args.dry_run:
        settings.dry_run = True

    run(settings, once=args.once)


if __name__ == "__main__":
    main()
