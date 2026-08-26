from datetime import datetime

from premarket_scanner.trigger import TriggerEngine, check_confirmation


def _t(base, minutes):
    from datetime import timedelta

    return base + timedelta(minutes=minutes)


def test_baseline_average_from_deltas():
    engine = TriggerEngine(multiplier=3.0, confirmation_minutes=3)
    # cumulative volume readings 15 min apart -> 4 deltas: 100,100,100,100
    for vol in (1000, 1100, 1200, 1300, 1400):
        engine.record_baseline_reading("AAPL", vol)
    avgs = engine.finalize_baseline()
    assert avgs["AAPL"] == 100.0


def test_seed_baseline_restores_avg_for_fresh_engine():
    # Simulates a process restart mid-trigger-window: a brand new engine
    # with no baseline_deltas of its own gets seeded from persisted values.
    engine = TriggerEngine(multiplier=3.0, confirmation_minutes=3)
    engine.seed_baseline({"AAPL": 100.0})

    base = datetime(2026, 8, 21, 7, 30)
    r0 = engine.evaluate("AAPL", base, 5000)  # first reading, establishes last_cum_volume
    assert r0.trigger1_fired is False
    assert r0.baseline_avg == 100.0

    r1 = engine.evaluate("AAPL", _t(base, 1), 5500)  # +500 > 100*3=300 breakout
    assert r1.trigger1_fired is True


def test_no_baseline_data_means_no_trigger():
    engine = TriggerEngine(multiplier=3.0, confirmation_minutes=3)
    engine.finalize_baseline()  # ticker never seen
    base = datetime(2026, 8, 21, 7, 0)
    reading = engine.evaluate("XYZ", base, 500)
    assert reading.trigger1_fired is False
    assert reading.baseline_avg is None


def test_trigger1_fires_on_breakout_minute():
    engine = TriggerEngine(multiplier=3.0, confirmation_minutes=3)
    engine.record_baseline_reading("AAPL", 1000)
    engine.record_baseline_reading("AAPL", 1100)  # baseline delta = 100
    engine.finalize_baseline()

    base = datetime(2026, 8, 21, 7, 0)
    # first trigger-phase reading establishes last_cum_volume, no delta yet
    r0 = engine.evaluate("AAPL", base, 1100)
    assert r0.trigger1_fired is False

    # jump of 400 > 100 * 3.0 breakout level
    r1 = engine.evaluate("AAPL", _t(base, 1), 1500)
    assert r1.trigger1_fired is True
    assert r1.watching is True
    assert r1.trigger2_confirmed is False


def test_trigger2_confirms_when_elevated_for_full_window():
    engine = TriggerEngine(multiplier=3.0, confirmation_minutes=3)
    engine.record_baseline_reading("AAPL", 1000)
    engine.record_baseline_reading("AAPL", 1100)  # baseline avg = 100
    engine.finalize_baseline()

    base = datetime(2026, 8, 21, 7, 0)
    engine.evaluate("AAPL", base, 1100)
    r1 = engine.evaluate("AAPL", _t(base, 1), 1500)  # +400, breakout
    assert r1.trigger1_fired is True

    # 3 confirmation minutes, all deltas >= breakout level (300)
    engine.evaluate("AAPL", _t(base, 2), 1800)  # +300
    engine.evaluate("AAPL", _t(base, 3), 2150)  # +350
    r4 = engine.evaluate("AAPL", _t(base, 4), 2500)  # +350
    assert r4.trigger2_confirmed is True
    assert r4.watching is False


def test_trigger2_rejects_single_spike_that_fades():
    engine = TriggerEngine(multiplier=3.0, confirmation_minutes=3)
    engine.record_baseline_reading("AAPL", 1000)
    engine.record_baseline_reading("AAPL", 1100)  # baseline avg = 100
    engine.finalize_baseline()

    base = datetime(2026, 8, 21, 7, 0)
    engine.evaluate("AAPL", base, 1100)
    engine.evaluate("AAPL", _t(base, 1), 1500)  # +400 breakout

    # fades immediately and isn't increasing
    engine.evaluate("AAPL", _t(base, 2), 1520)  # +20
    engine.evaluate("AAPL", _t(base, 3), 1525)  # +5
    r4 = engine.evaluate("AAPL", _t(base, 4), 1528)  # +3
    assert r4.trigger2_confirmed is False
    assert r4.watching is False  # released back to idle, can re-arm


def test_check_confirmation_elevated_but_not_increasing():
    assert check_confirmation([300, 250, 320], breakout_level=200) is True


def test_check_confirmation_increasing_but_below_breakout():
    assert check_confirmation([50, 80, 120], breakout_level=200) is True


def test_check_confirmation_neither():
    assert check_confirmation([300, 50, 40], breakout_level=200) is False
