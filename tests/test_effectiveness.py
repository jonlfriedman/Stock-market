import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from premarket_scanner.config import Settings
from premarket_scanner.effectiveness import EffectivenessTracker
from premarket_scanner.storage import Storage


def _settings(**overrides) -> Settings:
    base = Settings(effectiveness_snapshot_minutes=15, scan_end_time="10:00")
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_schedule_creates_snapshots_until_scan_end():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        tracker = EffectivenessTracker(storage, _settings())

        trigger_time = datetime(2026, 8, 21, 9, 10)
        tracker.schedule("AAPL", trigger_time, 10.0)

        due = storage.due_effectiveness_snapshots(datetime(2026, 8, 21, 23, 59))
        offsets = sorted(row["offset_minutes"] for row in due)
        # 9:10 + 15,30,45 = 9:25/9:40/9:55 all <= 10:00; +60 = 10:10 > 10:00
        assert offsets == [15, 30, 45]
        storage.close()


def test_process_due_records_price_and_pct_change():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        tracker = EffectivenessTracker(storage, _settings())

        trigger_time = datetime(2026, 8, 21, 7, 0)
        tracker.schedule("AAPL", trigger_time, 10.0)

        due_time = trigger_time + timedelta(minutes=15)
        tracker.process_due(due_time, {"AAPL": 11.0})

        due = storage.due_effectiveness_snapshots(datetime(2026, 8, 21, 23, 59))
        remaining_offsets = sorted(row["offset_minutes"] for row in due)
        assert 15 not in remaining_offsets  # recorded, no longer pending
        assert 30 in remaining_offsets
        storage.close()


def test_process_due_skips_when_price_missing():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        tracker = EffectivenessTracker(storage, _settings())

        trigger_time = datetime(2026, 8, 21, 7, 0)
        tracker.schedule("AAPL", trigger_time, 10.0)

        due_time = trigger_time + timedelta(minutes=15)
        tracker.process_due(due_time, {})  # AAPL missing from this poll

        due = storage.due_effectiveness_snapshots(datetime(2026, 8, 21, 23, 59))
        assert any(row["offset_minutes"] == 15 for row in due)  # still pending
        storage.close()
