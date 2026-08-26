"""Persistence: SQLite for confirmed triggers / effectiveness tracking /
alert cooldowns, CSV for the per-minute diagnostic log.

The CSV log (every poll, every ticker, not just confirmed triggers) is
deliberate -- it's the raw data the diagnostic-first rollout is analyzed
from: whether the 7:00 AM broker-unlock effect is market-wide, how big it
is, and which tickers still stand out after accounting for it. See
scripts/diagnostic_report.py.
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS confirmed_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trigger_time TEXT NOT NULL,
    trigger_price REAL NOT NULL,
    baseline_avg_vol_per_min REAL NOT NULL,
    minute_volume REAL NOT NULL,
    alerted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_confirmed_triggers_ticker_time
    ON confirmed_triggers (ticker, trigger_time);

CREATE TABLE IF NOT EXISTS effectiveness_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trigger_time TEXT NOT NULL,
    trigger_price REAL NOT NULL,
    offset_minutes INTEGER NOT NULL,
    due_time TEXT NOT NULL,
    snapshot_time TEXT,
    price REAL,
    pct_change_from_trigger REAL,
    recorded INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_effectiveness_due
    ON effectiveness_snapshots (recorded, due_time);

CREATE TABLE IF NOT EXISTS baseline_averages (
    trade_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    baseline_avg_vol_per_min REAL NOT NULL,
    PRIMARY KEY (trade_date, ticker)
);
"""

SCAN_LOG_HEADER = [
    "timestamp",
    "phase",
    "ticker",
    "price",
    "cumulative_volume",
    "minute_volume",
    "baseline_avg_vol_per_min",
    "ratio_to_baseline",
    "trigger1_fired",
    "trigger2_confirmed",
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

    # --- Confirmed triggers / cooldown ---
    def last_alert_time(self, ticker: str) -> datetime | None:
        cur = self._conn.execute(
            "SELECT trigger_time FROM confirmed_triggers WHERE ticker = ? "
            "ORDER BY trigger_time DESC LIMIT 1",
            (ticker,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0])

    def record_confirmed_trigger(
        self,
        ticker: str,
        trigger_time: datetime,
        trigger_price: float,
        baseline_avg_vol_per_min: float,
        minute_volume: float,
        alerted: bool,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO confirmed_triggers "
            "(ticker, trigger_time, trigger_price, baseline_avg_vol_per_min, minute_volume, alerted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                ticker,
                trigger_time.isoformat(),
                trigger_price,
                baseline_avg_vol_per_min,
                minute_volume,
                int(alerted),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    # --- Effectiveness tracking ---
    def add_effectiveness_pending(
        self,
        ticker: str,
        trigger_time: datetime,
        trigger_price: float,
        offset_minutes: int,
        due_time: datetime,
    ) -> None:
        self._conn.execute(
            "INSERT INTO effectiveness_snapshots "
            "(ticker, trigger_time, trigger_price, offset_minutes, due_time) VALUES (?, ?, ?, ?, ?)",
            (ticker, trigger_time.isoformat(), trigger_price, offset_minutes, due_time.isoformat()),
        )
        self._conn.commit()

    def due_effectiveness_snapshots(self, now: datetime) -> list[dict]:
        cur = self._conn.execute(
            "SELECT id, ticker, trigger_time, trigger_price, offset_minutes, due_time "
            "FROM effectiveness_snapshots WHERE recorded = 0 AND due_time <= ?",
            (now.isoformat(),),
        )
        cols = ["id", "ticker", "trigger_time", "trigger_price", "offset_minutes", "due_time"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def record_effectiveness_snapshot(
        self, snapshot_id: int, snapshot_time: datetime, price: float, pct_change_from_trigger: float
    ) -> None:
        self._conn.execute(
            "UPDATE effectiveness_snapshots SET recorded = 1, snapshot_time = ?, price = ?, "
            "pct_change_from_trigger = ? WHERE id = ?",
            (snapshot_time.isoformat(), price, pct_change_from_trigger, snapshot_id),
        )
        self._conn.commit()

    # --- Baseline persistence (survives a mid-session process restart) ---
    def save_baseline_averages(self, trade_date: str, averages: dict[str, float | None]) -> None:
        rows = [(trade_date, ticker, avg) for ticker, avg in averages.items() if avg is not None and avg > 0]
        if not rows:
            return
        self._conn.executemany(
            "INSERT OR REPLACE INTO baseline_averages (trade_date, ticker, baseline_avg_vol_per_min) "
            "VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def load_baseline_averages(self, trade_date: str) -> dict[str, float]:
        cur = self._conn.execute(
            "SELECT ticker, baseline_avg_vol_per_min FROM baseline_averages WHERE trade_date = ?",
            (trade_date,),
        )
        return {ticker: avg for ticker, avg in cur.fetchall()}

    # --- Diagnostic log (plain CSV, one file per day) ---
    def append_scan_log(self, trade_date: str, row: dict) -> None:
        path = self.data_dir / "logs" / f"scan_{trade_date}.csv"
        is_new = not path.exists()
        with path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SCAN_LOG_HEADER)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
