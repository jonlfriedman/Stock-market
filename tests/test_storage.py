import tempfile
from pathlib import Path

from premarket_scanner.storage import Storage


def test_save_and_load_baseline_averages_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        storage.save_baseline_averages("2026-08-26", {"AAPL": 100.0, "MSFT": 250.5})

        loaded = storage.load_baseline_averages("2026-08-26")
        assert loaded == {"AAPL": 100.0, "MSFT": 250.5}
        storage.close()


def test_load_baseline_averages_empty_for_unknown_date():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        assert storage.load_baseline_averages("2026-08-27") == {}
        storage.close()


def test_save_baseline_averages_skips_none_and_nonpositive():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        storage.save_baseline_averages("2026-08-26", {"AAPL": None, "ZERO": 0.0, "MSFT": 50.0})

        loaded = storage.load_baseline_averages("2026-08-26")
        assert loaded == {"MSFT": 50.0}
        storage.close()


def test_save_baseline_averages_is_scoped_per_trade_date():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        storage.save_baseline_averages("2026-08-25", {"AAPL": 100.0})
        storage.save_baseline_averages("2026-08-26", {"AAPL": 200.0})

        assert storage.load_baseline_averages("2026-08-25") == {"AAPL": 100.0}
        assert storage.load_baseline_averages("2026-08-26") == {"AAPL": 200.0}
        storage.close()
