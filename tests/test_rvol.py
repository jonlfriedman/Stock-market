import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from premarket_scanner.config import Settings
from premarket_scanner.rvol import RvolCalculator, time_bucket
from premarket_scanner.storage import Storage


def _settings(**overrides) -> Settings:
    base = Settings(rvol_min_history_days=3, rvol_time_bucket_minutes=5, rvol_lookback_days=20)
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_time_bucket_rounds_down():
    dt = datetime(2026, 8, 21, 4, 7)
    assert time_bucket(dt, 5) == "04:05"
    dt2 = datetime(2026, 8, 21, 4, 4)
    assert time_bucket(dt2, 5) == "04:00"


def test_falls_back_to_finviz_static_before_bootstrap():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        settings = _settings()
        calc = RvolCalculator(storage, settings)
        now = datetime(2026, 8, 21, 4, 5)
        result = calc.compute("AAPL", now, cumulative_volume=100_000, fallback_rel_volume=2.5)
        assert result.source == "finviz_static"
        assert result.value == 2.5
        storage.close()


def test_uses_self_built_history_once_bootstrapped():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        settings = _settings()
        calc = RvolCalculator(storage, settings)

        base_day = datetime(2026, 8, 10, 4, 5)
        for i in range(5):
            day = base_day + timedelta(days=i)
            storage.record_volume_snapshot("AAPL", day.date().isoformat(), "04:05", 10_000, 10.0)

        now = datetime(2026, 8, 21, 4, 5)
        result = calc.compute("AAPL", now, cumulative_volume=50_000, fallback_rel_volume=1.1)
        assert result.source == "history"
        assert result.value == 5.0  # 50000 / avg(10000)
        storage.close()


def test_unavailable_when_no_history_and_no_fallback():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        settings = _settings()
        calc = RvolCalculator(storage, settings)
        now = datetime(2026, 8, 21, 4, 5)
        result = calc.compute("NEWCO", now, cumulative_volume=1000, fallback_rel_volume=None)
        assert result.source == "unavailable"
        assert result.value is None
