from datetime import datetime

from premarket_scanner.config import Settings
from premarket_scanner.scanner import current_phase, seconds_until_next_window, within_scan_window


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
