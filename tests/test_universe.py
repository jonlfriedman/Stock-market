import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from premarket_scanner.config import Settings
from premarket_scanner.finviz_client import TickerSnapshot
from premarket_scanner.universe import get_universe


def test_watchlist_profile_bypasses_screener():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            profile="watchlist",
            watchlist_tickers=("MSFT", "AAPL"),
            data_dir=Path(tmp),
        )
        tickers = get_universe(settings, datetime(2026, 8, 21, 6, 30))
        assert tickers == ["AAPL", "MSFT"]


def test_discovery_profile_fetches_and_caches():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(profile="discovery", finviz_api_key="KEY", data_dir=Path(tmp))
        now = datetime(2026, 8, 21, 6, 30)

        fake_snapshots = [
            TickerSnapshot(ticker="ZZZ", price=5.0, volume=1000, change_pct=1.0, timestamp=now),
            TickerSnapshot(ticker="AAA", price=2.0, volume=2000, change_pct=-1.0, timestamp=now),
        ]
        with patch("premarket_scanner.universe.finviz_client.fetch_universe_snapshot", return_value=fake_snapshots) as m:
            tickers = get_universe(settings, now)
            assert tickers == ["AAA", "ZZZ"]
            assert m.call_count == 1

            # second call same day should hit the cache, not fetch again
            tickers2 = get_universe(settings, now)
            assert tickers2 == ["AAA", "ZZZ"]
            assert m.call_count == 1
