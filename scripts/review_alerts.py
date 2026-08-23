#!/usr/bin/env python3
"""Print every alert fired so far, with what the price actually did afterward.

For the Phase-1 "run it a week, then reassess" review: each alert's
outcome_15m/30m/60m columns are the % price change from the moment of the
alert to that many minutes later (filled in automatically as time passes --
see Storage.backfill_alert_outcomes). A blank outcome just means not enough
time has passed yet to fill it in, not missing data.

Usage:
    python scripts/review_alerts.py                # reads DATA_DIR from .env
    python scripts/review_alerts.py /path/to/data
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from premarket_scanner.config import load_settings


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "  --  "
    return f"{value:+6.2f}%"


def main() -> None:
    if len(sys.argv) > 1:
        data_dir = Path(sys.argv[1])
    else:
        data_dir = load_settings().data_dir

    db_path = data_dir / "scanner.db"
    if not db_path.exists():
        print(f"No database found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT ticker, alert_time, score, acceleration, rvol, price_at_alert, "
        "outcome_15m, outcome_30m, outcome_60m FROM alerts ORDER BY alert_time"
    ).fetchall()
    conn.close()

    if not rows:
        print("No alerts recorded yet.")
        return

    print(
        f"{'Ticker':<8}{'Alert Time':<22}{'Score':>7}{'Accel':>7}{'RVOL':>7}"
        f"{'Price':>9}{'+15m':>9}{'+30m':>9}{'+60m':>9}"
    )
    print("-" * 88)
    resolved_60m = []
    for ticker, alert_time, score, accel, rvol, price, o15, o30, o60 in rows:
        print(
            f"{ticker:<8}{alert_time:<22}{score:>7.2f}{accel:>7.2f}{rvol:>7.2f}"
            f"{price:>9.2f}{fmt_pct(o15):>9}{fmt_pct(o30):>9}{fmt_pct(o60):>9}"
        )
        if o60 is not None:
            resolved_60m.append(o60)

    print("-" * 88)
    print(f"{len(rows)} alert(s) total, {len(resolved_60m)} with a full 60-minute outcome so far.")
    if resolved_60m:
        avg = sum(resolved_60m) / len(resolved_60m)
        up = sum(1 for v in resolved_60m if v > 0)
        print(
            f"Of those: average 60-min price change {avg:+.2f}%, "
            f"{up}/{len(resolved_60m)} were up 60 minutes after the alert."
        )


if __name__ == "__main__":
    main()
