"""Configuration loading for the scanner.

All tunables live here so threshold tuning after the diagnostic week (see
README) means editing a .env file, not code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a listed dependency
    load_dotenv = None

DEFAULT_UNIVERSE_FILTER = "fa_pfcf_u20,ind_stocksonly,sh_avgvol_o300,sh_price_1to10"


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


@dataclass
class FieldMap:
    """Finviz CSV header names, overridable once the real headers are known.

    Finviz Elite's export column IDs (the numeric `c=` codes) aren't
    officially documented. Rather than guess them, the client parses the
    CSV by its header row text and this map says which header holds which
    value. Run scripts/discover_finviz_columns.py once to see the actual
    headers and override any of these via env vars if they differ.
    """

    ticker: str = "Ticker"
    price: str = "Price"
    volume: str = "Volume"
    change_pct: str = "Change"


@dataclass
class Settings:
    # --- Finviz ---
    finviz_api_key: str = ""
    finviz_view: str = "111"
    finviz_ft: str = "4"
    universe_filter: str = DEFAULT_UNIVERSE_FILTER
    field_map: FieldMap = field(default_factory=FieldMap)
    ticker_chunk_size: int = 200

    # --- Profile ---
    profile: str = "discovery"
    watchlist_tickers: tuple[str, ...] = ()

    # --- Schedule (all times in `timezone`, HH:MM 24h) ---
    timezone: str = "America/New_York"
    universe_fetch_time: str = "06:30"  # universe screen must complete before baseline_start_time
    baseline_start_time: str = "06:45"  # Phase 1 start
    trigger_start_time: str = "07:00"  # Phase 2 start (also broker-unlock time)
    scan_end_time: str = "10:00"  # end of Phase 2 + effectiveness tracking
    poll_interval_seconds: int = 60

    # --- Two-phase trigger logic ---
    # Multiplier is TBD from the diagnostic week (see README) -- this default
    # is a starting point, not a validated number.
    trigger_multiplier: float = 3.0
    confirmation_minutes: int = 3

    # --- Alerting ---
    alert_cooldown_minutes: int = 30
    # Diagnostic-first gate: must be deliberately flipped to true in .env
    # after the diagnostic week confirms the trigger logic. Defaults to
    # false so a fresh checkout never sends SMS by accident.
    live_alerting_enabled: bool = False
    dry_run: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_to_numbers: tuple[str, ...] = ()

    # --- Effectiveness tracking ---
    effectiveness_snapshot_minutes: int = 15

    # --- Storage ---
    data_dir: Path = Path("data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "scanner.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def universe_cache_dir(self) -> Path:
        return self.data_dir / "universe"


def load_settings(env_path: str | Path | None = None) -> Settings:
    if load_dotenv is not None:
        load_dotenv(dotenv_path=env_path, override=False)

    env = os.environ
    profile = env.get("SCANNER_PROFILE", "discovery").strip().lower()

    watchlist_raw = env.get("FINVIZ_WATCHLIST_TICKERS", "")
    watchlist_tickers = tuple(t.strip().upper() for t in watchlist_raw.split(",") if t.strip())

    to_numbers_raw = env.get("TWILIO_TO_NUMBERS", "")
    to_numbers = tuple(n.strip() for n in to_numbers_raw.split(",") if n.strip())

    field_map = FieldMap(
        ticker=env.get("FINVIZ_FIELD_TICKER", FieldMap.ticker),
        price=env.get("FINVIZ_FIELD_PRICE", FieldMap.price),
        volume=env.get("FINVIZ_FIELD_VOLUME", FieldMap.volume),
        change_pct=env.get("FINVIZ_FIELD_CHANGE", FieldMap.change_pct),
    )

    return Settings(
        finviz_api_key=env.get("FINVIZ_API_KEY", ""),
        finviz_view=env.get("FINVIZ_VIEW", "111"),
        finviz_ft=env.get("FINVIZ_FT", "4"),
        universe_filter=env.get("FINVIZ_UNIVERSE_FILTER", DEFAULT_UNIVERSE_FILTER),
        field_map=field_map,
        ticker_chunk_size=_int(env.get("FINVIZ_TICKER_CHUNK_SIZE"), 200),
        profile=profile,
        watchlist_tickers=watchlist_tickers,
        timezone=env.get("SCANNER_TIMEZONE", "America/New_York"),
        universe_fetch_time=env.get("UNIVERSE_FETCH_TIME", "06:30"),
        baseline_start_time=env.get("BASELINE_START_TIME", "06:45"),
        trigger_start_time=env.get("TRIGGER_START_TIME", "07:00"),
        scan_end_time=env.get("SCAN_END_TIME", "10:00"),
        poll_interval_seconds=_int(env.get("POLL_INTERVAL_SECONDS"), 60),
        trigger_multiplier=_float(env.get("TRIGGER_MULTIPLIER"), 3.0),
        confirmation_minutes=_int(env.get("CONFIRMATION_MINUTES"), 3),
        alert_cooldown_minutes=_int(env.get("ALERT_COOLDOWN_MINUTES"), 30),
        live_alerting_enabled=_bool(env.get("LIVE_ALERTING_ENABLED"), False),
        dry_run=_bool(env.get("DRY_RUN"), False),
        twilio_account_sid=env.get("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=env.get("TWILIO_AUTH_TOKEN", ""),
        twilio_from_number=env.get("TWILIO_FROM_NUMBER", ""),
        twilio_to_numbers=to_numbers,
        effectiveness_snapshot_minutes=_int(env.get("EFFECTIVENESS_SNAPSHOT_MINUTES"), 15),
        data_dir=Path(env.get("DATA_DIR", "data")),
    )
