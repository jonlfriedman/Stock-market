"""Rolling per-ticker buffer of recent volume/price snapshots.

Finviz's "Volume" column is cumulative day volume, not per-minute volume,
so per-minute window deltas are derived by differencing consecutive polls.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Snapshot:
    timestamp: datetime
    cumulative_volume: int
    price: float


class RollingBuffer:
    def __init__(self, window_minutes: int, poll_interval_seconds: int):
        self.window_minutes = window_minutes
        self.poll_interval_seconds = poll_interval_seconds
        maxlen = max(4, int((window_minutes * 60) / max(poll_interval_seconds, 1)) + 2)
        self._maxlen = maxlen
        self._data: dict[str, deque[Snapshot]] = {}

    def update(self, ticker: str, timestamp: datetime, cumulative_volume: int, price: float) -> None:
        buf = self._data.setdefault(ticker, deque(maxlen=self._maxlen))
        buf.append(Snapshot(timestamp, cumulative_volume, price))

    def warmed_up(self, ticker: str, min_minutes: int) -> bool:
        buf = self._data.get(ticker)
        if not buf or len(buf) < 2:
            return False
        span = buf[-1].timestamp - buf[0].timestamp
        return span >= timedelta(minutes=min_minutes)

    def get_window_deltas(self, ticker: str, n_windows: int) -> list[int] | None:
        """Last n_windows per-minute volume deltas, oldest first, or None if not enough data."""
        buf = self._data.get(ticker)
        if not buf or len(buf) < n_windows + 1:
            return None
        recent = list(buf)[-(n_windows + 1):]
        deltas = []
        for prev, curr in zip(recent, recent[1:]):
            deltas.append(max(0, curr.cumulative_volume - prev.cumulative_volume))
        return deltas

    def get_price_change_pct(self, ticker: str) -> float | None:
        buf = self._data.get(ticker)
        if not buf or len(buf) < 2:
            return None
        first, last = buf[0], buf[-1]
        if first.price == 0:
            return None
        return (last.price - first.price) / first.price * 100.0

    def known_tickers(self) -> list[str]:
        return list(self._data.keys())
