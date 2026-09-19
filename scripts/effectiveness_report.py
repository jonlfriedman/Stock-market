#!/usr/bin/env python3
"""Did a confirmed trigger actually predict a price move?

Reads confirmed_triggers + effectiveness_snapshots directly from
scanner.db (SQLite) and reports, at each snapshot offset (15/30/45/... min
after the trigger, per EFFECTIVENESS_SNAPSHOT_MINUTES), the average/median
% price change since the trigger -- both across all confirmed triggers and
after excluding ones whose baseline_avg_vol_per_min was below a floor
(retroactively filtering the near-zero-baseline noise identified in the
diagnostic week's data, without needing that fix deployed first).

Usage:
    .venv/bin/python scripts/effectiveness_report.py
    .venv/bin/python scripts/effectiveness_report.py --data-dir /opt/premarket-scanner/data
    .venv/bin/python scripts/effectiveness_report.py --min-baseline 10.0

No third-party dependencies -- stdlib only (sqlite3 + statistics).
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path


def describe(label: str, values: list[float]) -> str:
    if not values:
        return f"  {label}: (no data)"
    wins = sum(1 for v in values if v > 0)
    return (
        f"  {label}: n={len(values)} mean={statistics.mean(values):+.2f}% "
        f"median={statistics.median(values):+.2f}% "
        f"win_rate={wins / len(values):.0%} "
        f"min={min(values):+.2f}% max={max(values):+.2f}%"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default="data", help="scanner DATA_DIR (default: data)")
    parser.add_argument(
        "--min-baseline",
        type=float,
        default=10.0,
        help="exclude confirmed triggers with baseline_avg_vol_per_min below this (default: 10.0)",
    )
    args = parser.parse_args()

    db_path = Path(args.data_dir) / "scanner.db"
    if not db_path.exists():
        print(f"No database found at {db_path}")
        return

    conn = sqlite3.connect(db_path)

    total = conn.execute("SELECT COUNT(*) FROM confirmed_triggers").fetchone()[0]
    clean = conn.execute(
        "SELECT COUNT(*) FROM confirmed_triggers WHERE baseline_avg_vol_per_min >= ?", (args.min_baseline,)
    ).fetchone()[0]
    print(f"Confirmed triggers: {total} total, {clean} at/above baseline floor "
          f"({args.min_baseline}/min), {total - clean} excluded as noise")

    alerted = conn.execute("SELECT COUNT(*) FROM confirmed_triggers WHERE alerted = 1").fetchone()[0]
    print(f"Of those, actually alerted (live_alerting_enabled=true at the time): {alerted}")

    rows = conn.execute(
        """
        SELECT ct.baseline_avg_vol_per_min, es.offset_minutes, es.pct_change_from_trigger
        FROM effectiveness_snapshots es
        JOIN confirmed_triggers ct
          ON ct.ticker = es.ticker AND ct.trigger_time = es.trigger_time
        WHERE es.recorded = 1
        """
    ).fetchall()
    conn.close()

    if not rows:
        print("\nNo recorded effectiveness snapshots yet (they fill in over the course of each trading day).")
        return

    all_by_offset: dict[int, list[float]] = defaultdict(list)
    clean_by_offset: dict[int, list[float]] = defaultdict(list)
    for baseline_avg, offset, pct_change in rows:
        if pct_change is None:
            continue
        all_by_offset[offset].append(pct_change)
        if baseline_avg >= args.min_baseline:
            clean_by_offset[offset].append(pct_change)

    print("\n% price change since trigger, by minutes after trigger:")
    for offset in sorted(all_by_offset):
        print(f"\n+{offset} min:")
        print(describe("all confirmed triggers   ", all_by_offset[offset]))
        print(describe("excl. near-zero-baseline  ", clean_by_offset.get(offset, [])))


if __name__ == "__main__":
    main()
