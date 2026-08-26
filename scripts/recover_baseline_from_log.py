#!/usr/bin/env python3
"""One-off recovery: rebuild a day's finalized baseline from the CSV log.

If the service is restarted mid-trigger-window (after the 6:45-7:00
baseline window has already passed) on a build that predates baseline
persistence -- or the database itself got wiped -- the baseline can still
be reconstructed from the raw per-minute readings already written to
data/logs/scan_YYYY-MM-DD.csv during the baseline phase, and reseeded into
storage before restarting the service, recovering trigger detection for
the rest of that day instead of leaving it dark until tomorrow.

Usage:
    python scripts/recover_baseline_from_log.py 2026-08-26
    python scripts/recover_baseline_from_log.py   # defaults to today
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from premarket_scanner.config import load_settings
from premarket_scanner.storage import Storage


def compute_baseline_from_log(path: Path) -> dict[str, float]:
    readings: dict[str, list[tuple[str, float]]] = defaultdict(list)
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["phase"] != "baseline":
                continue
            readings[row["ticker"]].append((row["timestamp"], float(row["cumulative_volume"])))

    averages: dict[str, float] = {}
    for ticker, points in readings.items():
        points.sort(key=lambda p: p[0])
        deltas = [max(0.0, curr - prev) for (_, prev), (_, curr) in zip(points, points[1:])]
        if deltas:
            averages[ticker] = sum(deltas) / len(deltas)
    return averages


def main() -> None:
    trade_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    settings = load_settings()
    log_path = settings.logs_dir / f"scan_{trade_date}.csv"

    if not log_path.exists():
        print(f"No log found at {log_path}")
        sys.exit(1)

    averages = compute_baseline_from_log(log_path)
    if not averages:
        print(f"No baseline-phase rows found for {trade_date} in {log_path}")
        sys.exit(1)

    storage = Storage(settings.data_dir)
    storage.save_baseline_averages(trade_date, averages)
    storage.close()

    print(f"Recovered baseline for {len(averages)} tickers on {trade_date}, saved to {settings.db_path}")
    for ticker, avg in list(averages.items())[:5]:
        print(f"  {ticker}: {avg:.1f} vol/min")


if __name__ == "__main__":
    main()
