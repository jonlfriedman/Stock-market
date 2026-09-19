#!/usr/bin/env python3
"""Retroactively test the price-direction confirmation hypothesis against
data already collected -- no code deploy needed.

trigger.py's confirmation logic historically confirmed on volume alone.
This reconstructs, from the existing data/logs/scan_*.csv files, what each
confirmed trigger's price was at the original breakout (trigger1_fired)
minute vs. at the moment it confirmed, then joins to
data/scanner.db's effectiveness_snapshots (via confirmed_triggers) to
compare forward returns for triggers that would/wouldn't have also passed
a price-direction gate (price higher at confirmation than at breakout).

Reconstruction logic mirrors TriggerEngine's state machine per ticker per
day: the most recent trigger1_fired row for a ticker is that ticker's open
breakout until the next trigger2_confirmed row resolves it (or a fresh
trigger1_fired row replaces it, if the prior watch resolved to a reject
that isn't distinguishable in the log from "still watching").

Usage:
    .venv/bin/python scripts/price_direction_backtest.py
    .venv/bin/python scripts/price_direction_backtest.py --data-dir /opt/premarket-scanner/data
    .venv/bin/python scripts/price_direction_backtest.py --min-baseline 10.0

No third-party dependencies -- stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path


def to_bool(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def reconstruct_confirmations(log_dir: Path) -> list[dict]:
    """Returns one dict per confirmed trigger: ticker, confirm_time,
    confirm_price, breakout_price, baseline_avg_vol_per_min."""
    confirmations = []
    for path in sorted(log_dir.glob("scan_*.csv")):
        pending_breakout_price: dict[str, float] = {}
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row.get("phase") != "trigger":
                    continue
                ticker = row["ticker"]
                price = to_float(row.get("price"))
                if to_bool(row.get("trigger1_fired")) and price is not None:
                    pending_breakout_price[ticker] = price
                if to_bool(row.get("trigger2_confirmed")):
                    breakout_price = pending_breakout_price.pop(ticker, None)
                    if breakout_price is None or price is None:
                        continue  # incomplete data (e.g. log starts mid-watch)
                    confirmations.append(
                        {
                            "ticker": ticker,
                            "confirm_time": row["timestamp"],
                            "confirm_price": price,
                            "breakout_price": breakout_price,
                            "baseline_avg_vol_per_min": to_float(row.get("baseline_avg_vol_per_min")) or 0.0,
                        }
                    )
    return confirmations


def describe(label: str, values: list[float]) -> str:
    if not values:
        return f"    {label}: (no data)"
    wins = sum(1 for v in values if v > 0)
    return (
        f"    {label}: n={len(values)} mean={statistics.mean(values):+.2f}% "
        f"median={statistics.median(values):+.2f}% win_rate={wins / len(values):.0%}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default="data", help="scanner DATA_DIR (default: data)")
    parser.add_argument("--min-baseline", type=float, default=10.0, help="baseline-volume floor (default: 10.0)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    log_dir = data_dir / "logs"
    db_path = data_dir / "scanner.db"

    confirmations = reconstruct_confirmations(log_dir)
    if not confirmations:
        print(f"No confirmed triggers reconstructed from {log_dir}")
        return

    would_pass_price_gate = sum(1 for c in confirmations if c["confirm_price"] > c["breakout_price"])
    print(
        f"Reconstructed {len(confirmations)} confirmed triggers from the scan logs.\n"
        f"Of those, {would_pass_price_gate} ({would_pass_price_gate / len(confirmations):.0%}) "
        f"had price higher at confirmation than at breakout (would pass the new price gate)."
    )

    conn = sqlite3.connect(db_path)
    snapshots_by_key: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for ticker, trigger_time, offset, pct_change in conn.execute(
        "SELECT ticker, trigger_time, offset_minutes, pct_change_from_trigger "
        "FROM effectiveness_snapshots WHERE recorded = 1"
    ):
        if pct_change is not None:
            snapshots_by_key[(ticker, trigger_time)].append((offset, pct_change))
    conn.close()

    by_offset_price_confirmed: dict[int, list[float]] = defaultdict(list)
    by_offset_price_rejected: dict[int, list[float]] = defaultdict(list)
    by_offset_clean_price_confirmed: dict[int, list[float]] = defaultdict(list)
    matched = 0

    for c in confirmations:
        key = (c["ticker"], c["confirm_time"])
        snaps = snapshots_by_key.get(key)
        if not snaps:
            continue
        matched += 1
        price_confirmed = c["confirm_price"] > c["breakout_price"]
        clean = c["baseline_avg_vol_per_min"] >= args.min_baseline
        for offset, pct_change in snaps:
            if price_confirmed:
                by_offset_price_confirmed[offset].append(pct_change)
                if clean:
                    by_offset_clean_price_confirmed[offset].append(pct_change)
            else:
                by_offset_price_rejected[offset].append(pct_change)

    print(f"\nMatched {matched}/{len(confirmations)} confirmed triggers to recorded effectiveness snapshots.")
    print("\n% price change since confirmation, by minutes after confirmation:")
    for offset in sorted(set(by_offset_price_confirmed) | set(by_offset_price_rejected)):
        print(f"\n+{offset} min:")
        print(describe("price confirmed (would pass new gate)      ", by_offset_price_confirmed.get(offset, [])))
        print(describe("price rejected (would be excluded)         ", by_offset_price_rejected.get(offset, [])))
        print(describe("price confirmed AND above baseline floor   ", by_offset_clean_price_confirmed.get(offset, [])))


if __name__ == "__main__":
    main()
