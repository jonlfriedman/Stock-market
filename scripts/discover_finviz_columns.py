#!/usr/bin/env python3
"""One-off helper: fetch a Finviz Elite export URL and print its CSV headers.

Finviz's export column IDs aren't officially documented. Run this once
against your real export URL (see README for how to get one) to see the
exact header names it returns -- especially for premarket-specific columns
like premarket price/change/volume, whose exact labels vary by Finviz's
custom view configuration. Then set the matching FINVIZ_FIELD_* env vars
in .env if the defaults in config.FieldMap don't match.

Usage:
    python scripts/discover_finviz_columns.py "https://elite.finviz.com/export.ashx?..."
    python scripts/discover_finviz_columns.py   # reads FINVIZ_EXPORT_URL_DISCOVERY from .env
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from premarket_scanner.config import load_settings
from premarket_scanner.finviz_client import fetch_csv


def main() -> None:
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        settings = load_settings()
        url = settings.finviz_export_url

    if not url:
        print("No export URL given and none configured. Pass one as an argument or set")
        print("FINVIZ_EXPORT_URL_DISCOVERY in .env.")
        sys.exit(1)

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
        "\nIf any of Ticker/Price/Volume/Change/Rel Volume above don't match "
        "the defaults in premarket_scanner/config.py's FieldMap, set the "
        "corresponding FINVIZ_FIELD_* env var in .env to the exact header text shown."
    )


if __name__ == "__main__":
    main()
