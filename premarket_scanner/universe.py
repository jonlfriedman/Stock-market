"""Fixed session universe: the ticker list a scan session watches.

Run once before the baseline window starts (see build spec). The result is
cached to disk so a process restart mid-morning doesn't silently redraw a
different universe partway through a session -- everything after the first
successful fetch for a given trade date reuses the cached list.
"""
from __future__ import annotations

import logging
from datetime import date

from . import finviz_client
from .config import Settings

log = logging.getLogger(__name__)


def _cache_path(settings: Settings, trade_date: date):
    settings.universe_cache_dir.mkdir(parents=True, exist_ok=True)
    return settings.universe_cache_dir / f"universe_{trade_date.isoformat()}.txt"


def _load_cache(settings: Settings, trade_date: date) -> list[str] | None:
    path = _cache_path(settings, trade_date)
    if not path.exists():
        return None
    tickers = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    return tickers or None


def _save_cache(settings: Settings, trade_date: date, tickers: list[str]) -> None:
    path = _cache_path(settings, trade_date)
    path.write_text("\n".join(tickers) + "\n")


def get_universe(settings: Settings, now) -> list[str]:
    """Return the fixed ticker universe for this session.

    Watchlist profile bypasses the screener entirely and uses the
    explicitly configured ticker list. Discovery profile runs the Finviz
    universe screen (use #1) and caches the result for the trade date.
    """
    if settings.profile == "watchlist":
        return sorted(settings.watchlist_tickers)

    trade_date = now.date()
    cached = _load_cache(settings, trade_date)
    if cached is not None:
        return cached

    snapshots = finviz_client.fetch_universe_snapshot(settings, now)
    tickers = sorted({snap.ticker for snap in snapshots})
    log.info("Universe screen returned %d tickers for %s", len(tickers), trade_date.isoformat())
    _save_cache(settings, trade_date, tickers)
    return tickers
