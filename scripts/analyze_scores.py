#!/usr/bin/env python3
"""Summarize Phase-1 score logs (data/logs/scores_*.csv) to help tune
SCORE_THRESHOLD and friends, per the README's "Tuning" section.

Usage (on the droplet, from the repo root):

    .venv/bin/python scripts/analyze_scores.py
    .venv/bin/python scripts/analyze_scores.py --date 2026-09-03
    .venv/bin/python scripts/analyze_scores.py --data-dir /opt/premarket-scanner/data
    .venv/bin/python scripts/analyze_scores.py --top 30 --min-score 2.5

No third-party dependencies -- stdlib only, so it runs with the system
python3 too, not just the venv.
"""
from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

NUMERIC_FIELDS = ["price", "cumulative_volume", "acceleration_score", "rvol", "price_change_pct", "score"]
BOOL_FIELDS = ["sustained", "alerted"]


def load_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                for field in NUMERIC_FIELDS:
                    try:
                        row[field] = float(row[field])
                    except (TypeError, ValueError):
                        row[field] = float("nan")
                for field in BOOL_FIELDS:
                    row[field] = str(row.get(field, "")).strip().lower() in ("true", "1", "yes")
                row["_source_file"] = path.name
                rows.append(row)
    return rows


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def describe(label: str, values: list[float]) -> None:
    values = [v for v in values if v == v]  # drop NaN
    if not values:
        print(f"  {label}: (no data)")
        return
    print(
        f"  {label}: n={len(values)} min={min(values):.2f} "
        f"p50={percentile(values, 50):.2f} p90={percentile(values, 90):.2f} "
        f"p95={percentile(values, 95):.2f} max={max(values):.2f} "
        f"mean={statistics.mean(values):.2f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default="data", help="scanner DATA_DIR (default: data)")
    parser.add_argument("--date", help="only load scores_<date>.csv (YYYY-MM-DD); default: all files")
    parser.add_argument("--top", type=int, default=20, help="how many top-scoring rows to print (default: 20)")
    parser.add_argument("--min-score", type=float, default=None, help="only include rows with score >= this")
    args = parser.parse_args()

    log_dir = Path(args.data_dir) / "logs"
    if args.date:
        paths = [log_dir / f"scores_{args.date}.csv"]
        paths = [p for p in paths if p.exists()]
    else:
        paths = sorted(log_dir.glob("scores_*.csv"))

    if not paths:
        print(f"No score logs found under {log_dir}")
        return

    rows = load_rows(paths)
    if args.min_score is not None:
        rows = [r for r in rows if r["score"] >= args.min_score]

    print(f"Loaded {len(rows)} rows from {len(paths)} file(s): {', '.join(p.name for p in paths)}")
    tickers = {r["ticker"] for r in rows}
    print(f"Unique tickers: {len(tickers)}")

    alerted = [r for r in rows if r["alerted"]]
    not_alerted = [r for r in rows if not r["alerted"]]
    print(f"Alerted rows: {len(alerted)}  Not alerted: {len(not_alerted)}")

    print("\nScore distribution:")
    describe("all rows       ", [r["score"] for r in rows])
    describe("alerted rows   ", [r["score"] for r in alerted])
    describe("non-alerted    ", [r["score"] for r in not_alerted])

    print("\nComponent distributions (all rows):")
    describe("acceleration_score", [r["acceleration_score"] for r in rows])
    describe("rvol              ", [r["rvol"] for r in rows])
    describe("|price_change_pct|", [abs(r["price_change_pct"]) for r in rows])

    sustained_true = sum(1 for r in rows if r["sustained"])
    print(f"\nSustained acceleration gate passed: {sustained_true}/{len(rows)} rows")

    rvol_sources = defaultdict(int)
    for r in rows:
        rvol_sources[r.get("rvol_source") or "(blank)"] += 1
    print("RVOL source breakdown:", dict(rvol_sources))

    print(f"\nTop {args.top} rows by score:")
    print(f"  {'timestamp':<20} {'ticker':<8} {'score':>6} {'accel':>6} {'rvol':>6} {'chg%':>7} {'alerted':>8}")
    for r in sorted(rows, key=lambda r: r["score"], reverse=True)[: args.top]:
        print(
            f"  {r['timestamp']:<20} {r['ticker']:<8} {r['score']:>6.2f} "
            f"{r['acceleration_score']:>6.2f} {r['rvol']:>6.2f} {r['price_change_pct']:>7.2f} "
            f"{'yes' if r['alerted'] else 'no':>8}"
        )

    per_ticker_max = defaultdict(float)
    per_ticker_alerts = defaultdict(int)
    for r in rows:
        per_ticker_max[r["ticker"]] = max(per_ticker_max[r["ticker"]], r["score"])
        if r["alerted"]:
            per_ticker_alerts[r["ticker"]] += 1

    print(f"\nTop {min(args.top, len(per_ticker_max))} tickers by max score seen:")
    print(f"  {'ticker':<8} {'max_score':>10} {'alert_count':>12}")
    for ticker, max_score in sorted(per_ticker_max.items(), key=lambda kv: kv[1], reverse=True)[: args.top]:
        print(f"  {ticker:<8} {max_score:>10.2f} {per_ticker_alerts[ticker]:>12}")


if __name__ == "__main__":
    main()
