"""Effectiveness tracking, separate from alerting.

For every confirmed trigger, schedule price snapshots every
`snapshot_minutes` after the trigger, continuing until the day's
`scan_end_time` -- deliberately extending past 9:30 AM market open since
some moves may only materialize once regular-hours volume kicks in. This
log is for retrospective analysis (e.g. "average % price move N min after
a trigger"), independent of what the SMS alert itself contains.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .config import Settings
from .storage import Storage


def _end_of_day(now: datetime, scan_end_time: str) -> datetime:
    hour, minute = (int(x) for x in scan_end_time.split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


class EffectivenessTracker:
    def __init__(self, storage: Storage, settings: Settings):
        self.storage = storage
        self.interval_minutes = max(1, settings.effectiveness_snapshot_minutes)
        self.scan_end_time = settings.scan_end_time

    def schedule(self, ticker: str, trigger_time: datetime, trigger_price: float) -> None:
        cutoff = _end_of_day(trigger_time, self.scan_end_time)
        offset = self.interval_minutes
        while True:
            due_time = trigger_time + timedelta(minutes=offset)
            if due_time > cutoff:
                break
            self.storage.add_effectiveness_pending(ticker, trigger_time, trigger_price, offset, due_time)
            offset += self.interval_minutes

    def process_due(self, now: datetime, prices: dict[str, float]) -> None:
        for pending in self.storage.due_effectiveness_snapshots(now):
            price = prices.get(pending["ticker"])
            if price is None:
                continue
            trigger_price = pending["trigger_price"]
            pct_change = (price - trigger_price) / trigger_price * 100.0 if trigger_price else 0.0
            self.storage.record_effectiveness_snapshot(pending["id"], now, price, pct_change)
