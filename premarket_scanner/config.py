"""Configuration loading for the scanner.

All tunables live here so Phase-1 threshold tightening (see README) means
editing a .env file, not code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a listed dependency
    load_dotenv = None


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
    CSV by its header row text (whatever headers the user's saved export
    URL produces) and this map says which header holds which value. Run
    scripts/discover_finviz_columns.py once against your real export URL
    to see the actual headers -- especially for premarket-specific columns
    -- and override any of these via env vars if they differ.
    """

    ticker: str = "Ticker"
    price: str = "Price"
    volume: str = "Volume"
    change_pct: str = "Change"
    rel_volume: str = "Rel Volume"


@dataclass
class Settings:
    # --- Finviz ---
    finviz_export_url: str = ""
    field_map: FieldMap = field(default_factory=FieldMap)
    min_avg_volume_floor: float = 300_000.0  # documentation only; enforced by the Finviz filter itself

    # --- Schedule (all times in `timezone`) ---
    timezone: str = "America/New_York"
    scan_start_time: str = "04:00"
    scan_end_time: str = "09:30"
    trading_window_start: str = "07:00"
    poll_interval_seconds: int = 60

    # --- Rolling buffer / acceleration ---
    buffer_window_minutes: int = 15
    min_warmup_minutes: int = 15
    accel_windows: int = 4  # snapshots needed -> 3 consecutive ratios

    # --- RVOL (time-of-day baseline) ---
    rvol_time_bucket_minutes: int = 5
    rvol_min_history_days: int = 10  # bootstrap threshold before trusting our own history
    rvol_lookback_days: int = 20

    # --- Scoring weights (spec: acceleration weighted highest) ---
    weight_acceleration: float = 0.6
    weight_rvol: float = 0.25
    weight_price: float = 0.15
    score_threshold: float = 3.0  # Phase-1: deliberately loose

    # --- Alerting ---
    alert_cooldown_minutes: int = 30
    dry_run: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_to_numbers: tuple[str, ...] = ()

    # --- Storage ---
    data_dir: Path = Path("data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "scanner.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


def load_settings(env_path: str | Path | None = None) -> Settings:
    if load_dotenv is not None:
        load_dotenv(dotenv_path=env_path, override=False)

    env = os.environ
    profile = env.get("SCANNER_PROFILE", "discovery").strip().lower()

    if profile == "watchlist":
        export_url = env.get("FINVIZ_EXPORT_URL_WATCHLIST", "")
    else:
        export_url = env.get("FINVIZ_EXPORT_URL_DISCOVERY", env.get("FINVIZ_EXPORT_URL", ""))

    to_numbers_raw = env.get("TWILIO_TO_NUMBERS", "")
    to_numbers = tuple(n.strip() for n in to_numbers_raw.split(",") if n.strip())

    field_map = FieldMap(
        ticker=env.get("FINVIZ_FIELD_TICKER", FieldMap.ticker),
        price=env.get("FINVIZ_FIELD_PRICE", FieldMap.price),
        volume=env.get("FINVIZ_FIELD_VOLUME", FieldMap.volume),
        change_pct=env.get("FINVIZ_FIELD_CHANGE", FieldMap.change_pct),
        rel_volume=env.get("FINVIZ_FIELD_RELVOLUME", FieldMap.rel_volume),
    )

    return Settings(
        finviz_export_url=export_url,
        field_map=field_map,
        min_avg_volume_floor=_float(env.get("MIN_AVG_VOLUME_FLOOR"), 300_000.0),
        timezone=env.get("SCANNER_TIMEZONE", "America/New_York"),
        scan_start_time=env.get("SCAN_START_TIME", "04:00"),
        scan_end_time=env.get("SCAN_END_TIME", "09:30"),
        trading_window_start=env.get("TRADING_WINDOW_START", "07:00"),
        poll_interval_seconds=_int(env.get("POLL_INTERVAL_SECONDS"), 60),
        buffer_window_minutes=_int(env.get("BUFFER_WINDOW_MINUTES"), 15),
        min_warmup_minutes=_int(env.get("MIN_WARMUP_MINUTES"), 15),
        accel_windows=_int(env.get("ACCEL_WINDOWS"), 4),
        rvol_time_bucket_minutes=_int(env.get("RVOL_TIME_BUCKET_MINUTES"), 5),
        rvol_min_history_days=_int(env.get("RVOL_MIN_HISTORY_DAYS"), 10),
        rvol_lookback_days=_int(env.get("RVOL_LOOKBACK_DAYS"), 20),
        weight_acceleration=_float(env.get("WEIGHT_ACCELERATION"), 0.6),
        weight_rvol=_float(env.get("WEIGHT_RVOL"), 0.25),
        weight_price=_float(env.get("WEIGHT_PRICE"), 0.15),
        score_threshold=_float(env.get("SCORE_THRESHOLD"), 3.0),
        alert_cooldown_minutes=_int(env.get("ALERT_COOLDOWN_MINUTES"), 30),
        dry_run=_bool(env.get("DRY_RUN"), False),
        twilio_account_sid=env.get("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=env.get("TWILIO_AUTH_TOKEN", ""),
        twilio_from_number=env.get("TWILIO_FROM_NUMBER", ""),
        twilio_to_numbers=to_numbers,
        data_dir=Path(env.get("DATA_DIR", "data")),
    )
