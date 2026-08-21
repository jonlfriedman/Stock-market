"""Persistence: SQLite for RVOL history/alert cooldowns, CSV for Phase-1 analysis logs.

The SQLite volume_history table doubles as the scanner's own 20-trading-day
time-of-day baseline: since it polls every minute from 4:00 AM every trading
day anyway, it is collecting exactly the data needed for RVOL. See rvol.py.
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
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
    cumulative_volume INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker_time ON alerts (ticker, alert_time);
"""

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
    ) -> None:
        self._conn.execute(
            "INSERT INTO alerts "
            "(ticker, alert_time, score, acceleration, rvol, price_change_pct, cumulative_volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, alert_time.isoformat(), score, acceleration, rvol, price_change_pct, cumulative_volume),
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
