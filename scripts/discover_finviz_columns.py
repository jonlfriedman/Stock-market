#!/usr/bin/env python3
"""One-off helper: fetch the Finviz Elite universe screen and print its CSV headers.

Finviz's export column IDs aren't officially documented. Run this once
against your real FINVIZ_API_KEY (see README) to see the exact header
names it returns. Then set the matching FINVIZ_FIELD_* env vars in .env if
the defaults in config.FieldMap don't match.

Usage:
    python scripts/discover_finviz_columns.py   # uses FINVIZ_API_KEY / filters from .env
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

from premarket_scanner.config import load_settings
from premarket_scanner.finviz_client import build_universe_url, fetch_csv


def main() -> None:
    settings = load_settings()
    if not settings.finviz_api_key:
        print("FINVIZ_API_KEY is not set in .env. Set it and re-run.")
        sys.exit(1)

    url = build_universe_url(settings)
    text = fetch_csv(url)
    header_line = text.splitlines()[0]
    headers = [h.strip() for h in header_line.split(",")]

    print(f"Found {len(headers)} columns:\n")
    for i, h in enumerate(headers, 1):
        print(f"  {i:2d}. {h!r}")

    print("\nSample row(s):")
    for line in text.splitlines()[1:4]:
        print(f"  {line}")

    print(
        "\nIf any of Ticker/Price/Volume/Change above don't match the defaults "
        "in premarket_scanner/config.py's FieldMap, set the corresponding "
        "FINVIZ_FIELD_* env var in .env to the exact header text shown."
    )
    print(f"\n(fetched at {datetime.now().isoformat()})")


if __name__ == "__main__":
    main()
