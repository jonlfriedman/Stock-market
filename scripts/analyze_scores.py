#!/usr/bin/env python3
"""Summarize premarket scan logs (data/logs/scan_*.csv) -- the two-phase
trigger/confirmation log written by the current scanner build.

Columns expected: timestamp, phase, ticker, price, cumulative_volume,
minute_volume, baseline_avg_vol_per_min, ratio_to_baseline,
trigger1_fired, trigger2_confirmed, alerted

Usage (on the droplet, from the repo root):

    .venv/bin/python scripts/analyze_scores.py
    .venv/bin/python scripts/analyze_scores.py --date 2026-09-04
    .venv/bin/python scripts/analyze_scores.py --data-dir /opt/premarket-scanner/data
    .venv/bin/python scripts/analyze_scores.py --top 30

Streams rows file-by-file / row-by-row rather than loading everything into
memory -- these logs run to hundreds of thousands of rows per day and this
is meant to run comfortably on a small (512MB) droplet. No third-party
dependencies -- stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import heapq
import statistics
from array import array
from collections import defaultdict
from pathlib import Path


def to_bool(v: str | None) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def to_float(v: str | None) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def percentile(sorted_values, pct: float) -> float:
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def describe(label: str, values) -> None:
    vals = sorted(v for v in values if v == v)  # drop NaN
    if not vals:
        print(f"  {label}: (no data)")
        return
    print(
        f"  {label}: n={len(vals)} min={vals[0]:.2f} "
        f"p50={percentile(vals, 50):.2f} p90={percentile(vals, 90):.2f} "
        f"p95={percentile(vals, 95):.2f} max={vals[-1]:.2f} "
        f"mean={statistics.mean(vals):.2f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default="data", help="scanner DATA_DIR (default: data)")
    parser.add_argument("--date", help="only load scan_<date>.csv (YYYY-MM-DD); default: all files")
    parser.add_argument("--top", type=int, default=20, help="how many top rows/tickers to print (default: 20)")
    args = parser.parse_args()

    log_dir = Path(args.data_dir) / "logs"
    if args.date:
        paths = [p for p in [log_dir / f"scan_{args.date}.csv"] if p.exists()]
    else:
        paths = sorted(log_dir.glob("scan_*.csv"))

    if not paths:
        print(f"No scan logs found under {log_dir}")
        return

    total_rows = 0
    tickers: set[str] = set()
    phase_counts: dict[str, int] = defaultdict(int)
    trigger1 = trigger2 = alerted = 0

    ratios = array("d")
    ratios_t1 = array("d")
    ratios_t2 = array("d")
    ratios_alerted = array("d")
    minute_vols = array("d")
    baseline_vols = array("d")

    per_ticker_max_ratio: dict[str, float] = defaultdict(float)
    per_ticker_alerts: dict[str, int] = defaultdict(int)

    top_rows: list[tuple] = []  # bounded min-heap, keyed on ratio_to_baseline

    for path in paths:
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                total_rows += 1
                ticker = row.get("ticker", "")
                tickers.add(ticker)
                phase_counts[row.get("phase") or "(blank)"] += 1

                ratio = to_float(row.get("ratio_to_baseline"))
                mv = to_float(row.get("minute_volume"))
                bv = to_float(row.get("baseline_avg_vol_per_min"))
                t1 = to_bool(row.get("trigger1_fired"))
                t2 = to_bool(row.get("trigger2_confirmed"))
                al = to_bool(row.get("alerted"))

                if ratio == ratio:  # not NaN
                    ratios.append(ratio)
                    if t1:
                        ratios_t1.append(ratio)
                    if t2:
                        ratios_t2.append(ratio)
                    if al:
                        ratios_alerted.append(ratio)
                    per_ticker_max_ratio[ticker] = max(per_ticker_max_ratio[ticker], ratio)
                if mv == mv:
                    minute_vols.append(mv)
                if bv == bv:
                    baseline_vols.append(bv)

                trigger1 += t1
                trigger2 += t2
                alerted += al
                if al:
                    per_ticker_alerts[ticker] += 1

                sort_key = ratio if ratio == ratio else float("-inf")
                entry = (sort_key, total_rows, row.get("timestamp", ""), ticker, mv, bv, t1, t2, al)
                if len(top_rows) < args.top:
                    heapq.heappush(top_rows, entry)
                elif sort_key > top_rows[0][0]:
                    heapq.heapreplace(top_rows, entry)

    print(f"Loaded {total_rows} rows from {len(paths)} file(s): {', '.join(p.name for p in paths)}")
    print(f"Unique tickers: {len(tickers)}")
    print(f"Phase breakdown: {dict(phase_counts)}")

    print()
    if total_rows:
        print(f"trigger1_fired:     {trigger1}/{total_rows} ({trigger1 / total_rows:.1%})")
        print(f"trigger2_confirmed: {trigger2}/{total_rows} ({trigger2 / total_rows:.1%})")
        print(f"alerted:            {alerted}/{total_rows} ({alerted / total_rows:.2%})")
    if trigger1:
        print(f"trigger1 -> trigger2 conversion: {trigger2 / trigger1:.1%}")
    if trigger2:
        print(f"trigger2 -> alerted conversion:  {alerted / trigger2:.1%}")

    print("\nratio_to_baseline distribution:")
    describe("all rows          ", ratios)
    describe("trigger1_fired    ", ratios_t1)
    describe("trigger2_confirmed", ratios_t2)
    describe("alerted           ", ratios_alerted)

    print("\nVolume distributions:")
    describe("minute_volume           ", minute_vols)
    describe("baseline_avg_vol_per_min", baseline_vols)

    print(f"\nTop {args.top} rows by ratio_to_baseline:")
    print(
        f"  {'timestamp':<20} {'ticker':<8} {'ratio':>7} {'min_vol':>10} "
        f"{'baseline':>10} {'t1':>4} {'t2':>4} {'alerted':>8}"
    )
    for ratio, _, ts, ticker, mv, bv, t1, t2, al in sorted(top_rows, reverse=True):
        print(
            f"  {ts:<20} {ticker:<8} {ratio:>7.2f} {mv:>10.0f} {bv:>10.1f} "
            f"{'y' if t1 else 'n':>4} {'y' if t2 else 'n':>4} {'yes' if al else 'no':>8}"
        )

    print(f"\nTop {min(args.top, len(per_ticker_max_ratio))} tickers by max ratio_to_baseline:")
    print(f"  {'ticker':<8} {'max_ratio':>10} {'alert_count':>12}")
    for ticker, max_ratio in sorted(per_ticker_max_ratio.items(), key=lambda kv: kv[1], reverse=True)[: args.top]:
        print(f"  {ticker:<8} {max_ratio:>10.2f} {per_ticker_alerts[ticker]:>12}")


if __name__ == "__main__":
    main()
