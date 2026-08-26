import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from premarket_scanner.alerts import PushoverAlerter
from premarket_scanner.config import Settings
from premarket_scanner.effectiveness import EffectivenessTracker
from premarket_scanner.finviz_client import TickerSnapshot
from premarket_scanner.scanner import ScanState, current_phase, poll_once, seconds_until_next_window, within_scan_window
from premarket_scanner.storage import Storage


def _settings() -> Settings:
    return Settings(
        universe_fetch_time="06:30",
        baseline_start_time="06:45",
        trigger_start_time="07:00",
        scan_end_time="10:00",
    )


def test_within_scan_window_weekday_in_range():
    now = datetime(2026, 8, 21, 7, 30)  # Friday
    assert within_scan_window(now, _settings()) is True


def test_within_scan_window_before_start():
    now = datetime(2026, 8, 21, 6, 29)
    assert within_scan_window(now, _settings()) is False


def test_within_scan_window_after_end():
    now = datetime(2026, 8, 21, 10, 1)
    assert within_scan_window(now, _settings()) is False


def test_within_scan_window_weekend_excluded():
    now = datetime(2026, 8, 22, 7, 30)  # Saturday
    assert within_scan_window(now, _settings()) is False


def test_seconds_until_next_window_same_day():
    now = datetime(2026, 8, 21, 1, 0)  # Friday, before start
    secs = seconds_until_next_window(now, _settings())
    assert secs == 5 * 3600 + 30 * 60  # 06:30 - 01:00


def test_seconds_until_next_window_skips_weekend():
    now = datetime(2026, 8, 21, 11, 0)  # Friday, after end
    secs = seconds_until_next_window(now, _settings())
    # Next window is Monday 06:30 -> Fri 11:00 to Mon 06:30 = 2 days 19.5 hours
    expected_seconds = 2 * 86400 + 19 * 3600 + 30 * 60
    assert secs == expected_seconds


def test_current_phase_pre_baseline():
    now = datetime(2026, 8, 21, 6, 40)
    assert current_phase(now, _settings()) == "pre_baseline"


def test_current_phase_baseline():
    now = datetime(2026, 8, 21, 6, 50)
    assert current_phase(now, _settings()) == "baseline"


def test_current_phase_trigger():
    now = datetime(2026, 8, 21, 7, 5)
    assert current_phase(now, _settings()) == "trigger"


def test_current_phase_trigger_extends_to_scan_end():
    now = datetime(2026, 8, 21, 9, 45)
    assert current_phase(now, _settings()) == "trigger"


def test_current_phase_outside():
    now = datetime(2026, 8, 21, 10, 30)
    assert current_phase(now, _settings()) == "outside"


def test_process_restart_mid_trigger_window_restores_baseline_from_storage():
    """Reproduces the real incident: the service gets restarted at, say,
    7:48 AM -- after the 6:45-7:00 baseline window has already passed. A
    brand new in-memory TriggerEngine has no baseline data of its own, but
    a *previous* process instance already finalized and persisted one for
    today, so it should be restored rather than trigger detection going
    dark for the rest of the day."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            profile="watchlist",
            watchlist_tickers=("AAPL",),
            data_dir=Path(tmp),
            trigger_multiplier=3.0,
            confirmation_minutes=3,
        )
        storage = Storage(settings.data_dir)
        # Simulate: an earlier process instance already finalized today's baseline.
        storage.save_baseline_averages("2026-08-26", {"AAPL": 100.0})

        alerter = PushoverAlerter(settings, storage)
        effectiveness = EffectivenessTracker(storage, settings)
        state = ScanState()  # fresh, as if the process just started

        now = datetime(2026, 8, 26, 7, 48)  # well past baseline_start_time
        with patch(
            "premarket_scanner.scanner.finviz_client.fetch_quotes",
            return_value=[TickerSnapshot("AAPL", 11.0, 5000, 0.5, now)],
        ):
            poll_once(settings, storage, state, alerter, effectiveness, now)

        assert state.baseline_finalized is True
        assert state.engine.evaluate("AAPL", now, 5000).baseline_avg == 100.0
        storage.close()
