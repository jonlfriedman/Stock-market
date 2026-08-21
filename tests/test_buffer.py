from datetime import datetime, timedelta

from premarket_scanner.buffer import RollingBuffer


def _t(base, minutes):
    return base + timedelta(minutes=minutes)


def test_warmed_up_requires_span():
    buf = RollingBuffer(window_minutes=15, poll_interval_seconds=60)
    base = datetime(2026, 8, 21, 4, 0)
    buf.update("AAPL", base, 1000, 10.0)
    assert buf.warmed_up("AAPL", 15) is False

    buf.update("AAPL", _t(base, 16), 2000, 10.5)
    assert buf.warmed_up("AAPL", 15) is True


def test_window_deltas_ordering_and_math():
    buf = RollingBuffer(window_minutes=15, poll_interval_seconds=60)
    base = datetime(2026, 8, 21, 4, 0)
    cumulative = [1000, 1100, 1300, 1600, 2000]
    for i, vol in enumerate(cumulative):
        buf.update("AAPL", _t(base, i), vol, 10.0)

    deltas = buf.get_window_deltas("AAPL", 4)
    assert deltas == [100, 200, 300, 400]


def test_window_deltas_none_when_insufficient():
    buf = RollingBuffer(window_minutes=15, poll_interval_seconds=60)
    base = datetime(2026, 8, 21, 4, 0)
    buf.update("AAPL", base, 1000, 10.0)
    buf.update("AAPL", _t(base, 1), 1100, 10.0)
    assert buf.get_window_deltas("AAPL", 4) is None


def test_price_change_pct():
    buf = RollingBuffer(window_minutes=15, poll_interval_seconds=60)
    base = datetime(2026, 8, 21, 4, 0)
    buf.update("AAPL", base, 1000, 10.0)
    buf.update("AAPL", _t(base, 5), 1500, 11.0)
    pct = buf.get_price_change_pct("AAPL")
    assert round(pct, 4) == 10.0


def test_buffer_maxlen_evicts_oldest():
    buf = RollingBuffer(window_minutes=2, poll_interval_seconds=60)
    base = datetime(2026, 8, 21, 4, 0)
    for i in range(20):
        buf.update("AAPL", _t(base, i), 1000 + i * 100, 10.0)
    # buffer should not grow unbounded
    assert len(buf._data["AAPL"]) <= buf._maxlen
