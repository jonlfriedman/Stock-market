"""Relative volume vs. the same time-of-day over the last N trading days.

Building a true time-of-day baseline requires historical intraday premarket
volume bucketed by minute -- data the scanner has no external source for.
Instead, the scanner bootstraps its own baseline from what it collects each
day (storage.volume_history): once a ticker has enough historical
same-time-bucket samples, RVOL is computed from that. Until then, it falls
back to Finviz's own "Relative Volume" column (a static day-level ratio) so
the scanner is useful from day one, not just after the RVOL_MIN_HISTORY_DAYS
warm-up period.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import Settings
from .storage import Storage


def time_bucket(dt: datetime, bucket_minutes: int) -> str:
    total_minutes = dt.hour * 60 + dt.minute
    bucket_start = (total_minutes // bucket_minutes) * bucket_minutes
    return f"{bucket_start // 60:02d}:{bucket_start % 60:02d}"


@dataclass
class RvolResult:
    value: float | None
    source: str  # "history" | "finviz_static" | "unavailable"
    sample_count: int = 0


class RvolCalculator:
    def __init__(self, storage: Storage, settings: Settings):
        self.storage = storage
        self.settings = settings

    def compute(
        self,
        ticker: str,
        now: datetime,
        cumulative_volume: int,
        fallback_rel_volume: float | None,
    ) -> RvolResult:
        bucket = time_bucket(now, self.settings.rvol_time_bucket_minutes)
        trade_date = now.date().isoformat()
        history = self.storage.historical_bucket_volumes(
            ticker, bucket, self.settings.rvol_lookback_days, exclude_date=trade_date
        )
        if len(history) >= self.settings.rvol_min_history_days:
            nonzero = [v for v in history if v > 0]
            if nonzero:
                avg = sum(nonzero) / len(nonzero)
                if avg > 0:
                    return RvolResult(value=cumulative_volume / avg, source="history", sample_count=len(nonzero))

        if fallback_rel_volume is not None:
            return RvolResult(value=fallback_rel_volume, source="finviz_static", sample_count=len(history))

        return RvolResult(value=None, source="unavailable", sample_count=len(history))
