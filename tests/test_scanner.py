from datetime import datetime

from premarket_scanner.config import Settings
from premarket_scanner.scanner import seconds_until_next_window, within_scan_window


def _settings() -> Settings:
    return Settings(scan_start_time="04:00", scan_end_time="09:30")


def test_within_scan_window_weekday_in_range():
    now = datetime(2026, 8, 21, 6, 30)  # Friday
    assert within_scan_window(now, _settings()) is True


def test_within_scan_window_before_start():
    now = datetime(2026, 8, 21, 3, 59)
    assert within_scan_window(now, _settings()) is False


def test_within_scan_window_after_end():
    now = datetime(2026, 8, 21, 9, 31)
    assert within_scan_window(now, _settings()) is False


def test_within_scan_window_weekend_excluded():
    now = datetime(2026, 8, 22, 6, 30)  # Saturday
    assert within_scan_window(now, _settings()) is False


def test_seconds_until_next_window_same_day():
    now = datetime(2026, 8, 21, 1, 0)  # Friday, before start
    secs = seconds_until_next_window(now, _settings())
    assert secs == 3 * 3600  # 04:00 - 01:00


def test_seconds_until_next_window_skips_weekend():
    now = datetime(2026, 8, 21, 10, 0)  # Friday, after end
    secs = seconds_until_next_window(now, _settings())
    # Next window is Monday 04:00 -> Fri 10:00 to Mon 04:00 = 2 days 18 hours
    expected_days = 2
    expected_seconds = expected_days * 86400 + 18 * 3600
    assert secs == expected_seconds
