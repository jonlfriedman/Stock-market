#!/usr/bin/env python3
"""Diagnostic-week analysis helper (see README's "Diagnostic-First Rollout").

Reads the per-minute scan log(s) in data/logs/scan_*.csv and reports, for
the first few minutes of the trigger window (7:00 AM onward by default):

1. What fraction of the universe shows an elevated ratio_to_baseline --
   i.e. is the 7:00 AM step-up market-wide or only some tickers?
2. The cross-sectional median ratio_to_baseline in that window -- the
   rough size of any market-wide effect, useful as a normalization factor.
3. Which tickers' ratio is well above that median even after accounting
   for the crowd effect -- candidates for real trigger multiplier tuning.

Usage:
    python scripts/diagnostic_report.py                  # all logs in data/logs/
    python scripts/diagnostic_report.py 2026-08-25        # one trade date
    python scripts/diagnostic_report.py --minutes 5        # widen the window
    python scripts/diagnostic_report.py --standout-factor 3.0
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from premarket_scanner.config import load_settings


def _load_rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def analyze_file(path: Path, trigger_start: str, window_minutes: int, standout_factor: float) -> None:
    rows = _load_rows(path)
    trigger_rows = [r for r in rows if r["phase"] == "trigger" and r["ratio_to_baseline"]]
    if not trigger_rows:
        print(f"{path.name}: no trigger-phase rows with a ratio yet -- nothing to analyze.")
        return

    hour, minute = (int(x) for x in trigger_start.split(":"))
    first_ts = min(datetime.fromisoformat(r["timestamp"]) for r in trigger_rows)
    window_start = first_ts.replace(hour=hour, minute=minute, second=0, microsecond=0)
    window_end = window_start + timedelta(minutes=window_minutes)

    windowed = [
        r for r in trigger_rows if window_start <= datetime.fromisoformat(r["timestamp"]) < window_end
    ]
    if not windowed:
        print(f"{path.name}: no rows within {window_minutes} min of {trigger_start} -- nothing to analyze.")
        return

    per_ticker_ratios: dict[str, list[float]] = defaultdict(list)
    for r in windowed:
        per_ticker_ratios[r["ticker"]].append(float(r["ratio_to_baseline"]))

    per_ticker_avg = {t: statistics.mean(v) for t, v in per_ticker_ratios.items()}
    all_avgs = list(per_ticker_avg.values())
    median_ratio = statistics.median(all_avgs)
    mean_ratio = statistics.mean(all_avgs)
    pct_above_1_5x = sum(1 for v in all_avgs if v > 1.5) / len(all_avgs) * 100

    standouts = sorted(
        ((t, v) for t, v in per_ticker_avg.items() if median_ratio > 0 and v > median_ratio * standout_factor),
        key=lambda kv: kv[1],
        reverse=True,
    )

    print(f"=== {path.name} ({window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')}, "
          f"{len(per_ticker_avg)} tickers) ===")
    print(f"  median ratio_to_baseline: {median_ratio:.2f}x   mean: {mean_ratio:.2f}x")
    print(f"  {pct_above_1_5x:.0f}% of tickers show >1.5x their own baseline in this window")
    print(f"  (median/mean > 1x across most tickers suggests a market-wide broker-unlock "
          f"step-up; use median as a rough normalization factor)")
    if standouts:
        print(f"  standouts (> {standout_factor}x the cross-sectional median):")
        for ticker, ratio in standouts[:20]:
            print(f"    {ticker:<8} {ratio:.2f}x")
    else:
        print("  no standouts above the cross-sectional median at this factor")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trade_date", nargs="?", default=None, help="YYYY-MM-DD; default: all logs")
    parser.add_argument("--minutes", type=int, default=3, help="window width from trigger_start_time")
    parser.add_argument("--standout-factor", type=float, default=3.0)
    args = parser.parse_args()

    settings = load_settings()
    logs_dir = settings.logs_dir

    if args.trade_date:
        paths = [logs_dir / f"scan_{args.trade_date}.csv"]
    else:
        paths = sorted(logs_dir.glob("scan_*.csv"))

    if not paths or not any(p.exists() for p in paths):
        print(f"No scan logs found in {logs_dir}")
        sys.exit(1)

    for path in paths:
        if path.exists():
            analyze_file(path, settings.trigger_start_time, args.minutes, args.standout_factor)


if __name__ == "__main__":
    main()
