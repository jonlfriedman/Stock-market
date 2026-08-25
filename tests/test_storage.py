from datetime import datetime, timedelta

import pytest

from premarket_scanner.storage import Storage


@pytest.fixture
def storage(tmp_path):
    s = Storage(tmp_path)
    yield s
    s.close()


def test_backfill_alert_outcomes_fills_in_available_horizons(storage):
    alert_time = datetime(2026, 8, 24, 9, 0, 0)
    storage.record_alert(
        ticker="AAPL",
        alert_time=alert_time,
        score=3.5,
        acceleration=1.2,
        rvol=2.0,
        price_change_pct=4.0,
        cumulative_volume=500_000,
        price_at_alert=100.0,
    )

    # 15 minutes later, price rose to 110 -- record it in the same 5-min bucket
    # backfill will look up.
    later_15 = alert_time + timedelta(minutes=15)
    storage.record_volume_snapshot("AAPL", later_15.date().isoformat(), "09:15", 600_000, 110.0)

    storage.backfill_alert_outcomes(now=later_15, bucket_minutes=5)

    row = storage._conn.execute(
        "SELECT outcome_15m, outcome_30m, outcome_60m FROM alerts WHERE ticker = 'AAPL'"
    ).fetchone()
    assert row[0] == pytest.approx(10.0)  # (110-100)/100 * 100
    assert row[1] is None  # 30 min hasn't elapsed yet
    assert row[2] is None


def test_backfill_alert_outcomes_noop_when_price_missing(storage):
    alert_time = datetime(2026, 8, 24, 9, 0, 0)
    storage.record_alert(
        ticker="XYZ",
        alert_time=alert_time,
        score=3.5,
        acceleration=1.2,
        rvol=2.0,
        price_change_pct=4.0,
        cumulative_volume=500_000,
        price_at_alert=50.0,
    )

    # No volume_history row exists for +15m -- should just leave it unresolved,
    # not raise.
    storage.backfill_alert_outcomes(now=alert_time + timedelta(minutes=20), bucket_minutes=5)

    row = storage._conn.execute(
        "SELECT outcome_15m FROM alerts WHERE ticker = 'XYZ'"
    ).fetchone()
    assert row[0] is None


def test_price_near_returns_none_when_absent(storage):
    assert storage.price_near("NOPE", "2026-08-24", "09:00") is None
