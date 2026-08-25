import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from premarket_scanner.alerts import TwilioAlerter
from premarket_scanner.config import Settings
from premarket_scanner.storage import Storage


def _settings(**overrides) -> Settings:
    base = Settings(
        live_alerting_enabled=False,
        dry_run=False,
        twilio_account_sid="",
        twilio_auth_token="",
        twilio_from_number="",
        twilio_to_numbers=(),
        alert_cooldown_minutes=30,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_message_is_minimal_ticker_and_price_only():
    assert TwilioAlerter._format_message("AAPL", 123.456) == "AAPL $123.46"


def test_disabled_when_live_alerting_off_even_with_twilio_creds():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        settings = _settings(
            live_alerting_enabled=False,
            twilio_account_sid="sid",
            twilio_auth_token="tok",
            twilio_from_number="+1000",
            twilio_to_numbers=("+2000",),
        )
        alerter = TwilioAlerter(settings, storage)
        assert alerter.enabled is False
        sent = alerter.send("AAPL", 10.0)
        assert sent is False
        storage.close()


def test_disabled_in_dry_run_even_if_live_alerting_on():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        settings = _settings(
            live_alerting_enabled=True,
            dry_run=True,
            twilio_account_sid="sid",
            twilio_auth_token="tok",
            twilio_from_number="+1000",
            twilio_to_numbers=("+2000",),
        )
        alerter = TwilioAlerter(settings, storage)
        assert alerter.enabled is False
        storage.close()


def test_cooldown_elapsed_true_when_no_prior_trigger():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        alerter = TwilioAlerter(_settings(), storage)
        assert alerter.cooldown_elapsed("AAPL", datetime(2026, 8, 21, 7, 5)) is True
        storage.close()


def test_cooldown_blocks_within_window():
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(Path(tmp))
        alerter = TwilioAlerter(_settings(alert_cooldown_minutes=30), storage)
        t0 = datetime(2026, 8, 21, 7, 5)
        storage.record_confirmed_trigger("AAPL", t0, 10.0, 100.0, 400.0, alerted=True)

        assert alerter.cooldown_elapsed("AAPL", t0 + timedelta(minutes=10)) is False
        assert alerter.cooldown_elapsed("AAPL", t0 + timedelta(minutes=31)) is True
        storage.close()
