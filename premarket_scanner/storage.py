"""Persistence: SQLite for RVOL history/alert cooldowns, CSV for Phase-1 analysis logs.

The SQLite volume_history table doubles as the scanner's own 20-trading-day
time-of-day baseline: since it polls every minute from 4:00 AM every trading
day anyway, it is collecting exactly the data needed for RVOL. See rvol.py.
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS volume_history (
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    time_bucket TEXT NOT NULL,
    cumulative_volume INTEGER NOT NULL,
    price REAL NOT NULL,
    PRIMARY KEY (ticker, trade_date, time_bucket)
);
CREATE INDEX IF NOT EXISTS idx_volume_history_lookup
    ON volume_history (ticker, time_bucket, trade_date);

CREATE TABLE IF NOT EXISTS alerts (
    ticker TEXT NOT NULL,
    alert_time TEXT NOT NULL,
    score REAL NOT NULL,
    acceleration REAL NOT NULL,
    rvol REAL NOT NULL,
    price_change_pct REAL NOT NULL,
    cumulative_volume INTEGER NOT NULL,
    price_at_alert REAL NOT NULL DEFAULT 0,
    outcome_15m REAL,
    outcome_30m REAL,
    outcome_60m REAL
);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker_time ON alerts (ticker, alert_time);
"""

OUTCOME_HORIZON_MINUTES = (15, 30, 60)

SCORE_LOG_HEADER = [
    "timestamp",
    "ticker",
    "price",
    "cumulative_volume",
    "acceleration_score",
    "sustained",
    "rvol",
    "rvol_source",
    "price_change_pct",
    "score",
    "alerted",
]


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "scanner.db"
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate_alerts_columns()

    def _migrate_alerts_columns(self) -> None:
        """CREATE TABLE IF NOT EXISTS does nothing for a table that already
        exists under an older schema -- add any columns a pre-existing
        alerts table (from before outcome tracking was added) is missing."""
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(alerts)").fetchall()}
        migrations = {
            "price_at_alert": "ALTER TABLE alerts ADD COLUMN price_at_alert REAL NOT NULL DEFAULT 0",
            "outcome_15m": "ALTER TABLE alerts ADD COLUMN outcome_15m REAL",
            "outcome_30m": "ALTER TABLE alerts ADD COLUMN outcome_30m REAL",
            "outcome_60m": "ALTER TABLE alerts ADD COLUMN outcome_60m REAL",
        }
        for column, ddl in migrations.items():
            if column not in existing:
                self._conn.execute(ddl)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- RVOL history ---
    def record_volume_snapshot(
        self, ticker: str, trade_date: str, time_bucket: str, cumulative_volume: int, price: float
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO volume_history "
            "(ticker, trade_date, time_bucket, cumulative_volume, price) VALUES (?, ?, ?, ?, ?)",
            (ticker, trade_date, time_bucket, cumulative_volume, price),
        )
        self._conn.commit()

    def historical_bucket_volumes(
        self, ticker: str, time_bucket: str, lookback_days: int, exclude_date: str
    ) -> list[int]:
        cur = self._conn.execute(
            "SELECT cumulative_volume FROM volume_history "
            "WHERE ticker = ? AND time_bucket = ? AND trade_date != ? "
            "ORDER BY trade_date DESC LIMIT ?",
            (ticker, time_bucket, exclude_date, lookback_days),
        )
        return [row[0] for row in cur.fetchall()]

    # --- Alerts / cooldown ---
    def last_alert_time(self, ticker: str) -> datetime | None:
        cur = self._conn.execute(
            "SELECT alert_time FROM alerts WHERE ticker = ? ORDER BY alert_time DESC LIMIT 1",
            (ticker,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0])

    def record_alert(
        self,
        ticker: str,
        alert_time: datetime,
        score: float,
        acceleration: float,
        rvol: float,
        price_change_pct: float,
        cumulative_volume: int,
        price_at_alert: float,
    ) -> None:
        self._conn.execute(
            "INSERT INTO alerts "
            "(ticker, alert_time, score, acceleration, rvol, price_change_pct, cumulative_volume, price_at_alert) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ticker,
                alert_time.isoformat(),
                score,
                acceleration,
                rvol,
                price_change_pct,
                cumulative_volume,
                price_at_alert,
            ),
        )
        self._conn.commit()

    def price_near(self, ticker: str, trade_date: str, time_bucket: str) -> float | None:
        cur = self._conn.execute(
            "SELECT price FROM volume_history WHERE ticker = ? AND trade_date = ? AND time_bucket = ?",
            (ticker, trade_date, time_bucket),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def backfill_alert_outcomes(self, now: datetime, bucket_minutes: int) -> None:
        """Fill in outcome_15m/30m/60m (% price change since the alert) for past
        alerts, once enough time has elapsed and volume_history has a price for
        that later moment. Safe to call every poll cycle -- a no-op once every
        alert's horizons are either filled or still in the future."""
        from .rvol import time_bucket as _time_bucket

        cur = self._conn.execute(
            "SELECT rowid, ticker, alert_time, price_at_alert, outcome_15m, outcome_30m, outcome_60m "
            "FROM alerts WHERE outcome_60m IS NULL"
        )
        for rowid, ticker, alert_time_str, price_at_alert, o15, o30, o60 in cur.fetchall():
            alert_time = datetime.fromisoformat(alert_time_str)
            existing = {15: o15, 30: o30, 60: o60}
            updates: dict[str, float] = {}
            for minutes in OUTCOME_HORIZON_MINUTES:
                if existing[minutes] is not None:
                    continue
                target_time = alert_time + timedelta(minutes=minutes)
                if now < target_time:
                    continue
                trade_date = target_time.date().isoformat()
                bucket = _time_bucket(target_time, bucket_minutes)
                price = self.price_near(ticker, trade_date, bucket)
                if price is None or not price_at_alert:
                    continue
                updates[f"outcome_{minutes}m"] = (price - price_at_alert) / price_at_alert * 100.0
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                self._conn.execute(
                    f"UPDATE alerts SET {set_clause} WHERE rowid = ?",
                    (*updates.values(), rowid),
                )
        self._conn.commit()

    # --- Phase-1 analysis log (plain CSV, one file per day) ---
    def append_score_log(self, trade_date: str, row: dict) -> None:
        path = self.data_dir / "logs" / f"scores_{trade_date}.csv"
        is_new = not path.exists()
        with path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SCORE_LOG_HEADER)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
