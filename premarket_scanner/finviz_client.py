"""Finviz Elite screener export client.

Finviz Elite's API page (elite.finviz.com -> account menu -> API ->
Screener) documents the export flow directly, including numeric column IDs
for the `&c=` param -- see README for the full URL recipe (filters, pinned
columns, auth token). That full URL goes in FINVIZ_EXPORT_URL_DISCOVERY.
Legacy /export.ashx URLs still work too (301 redirect, followed by
requests). This module parses whatever CSV that URL returns by its header
row text rather than hardcoding column order -- see config.FieldMap and
scripts/discover_finviz_columns.py for a one-time sanity check that the
real header text matches.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

import requests

from .config import FieldMap

REQUEST_TIMEOUT_SECONDS = 30


class FinvizError(RuntimeError):
    pass


@dataclass
class TickerSnapshot:
    ticker: str
    price: float
    volume: int
    change_pct: float | None
    rel_volume: float | None
    timestamp: datetime


def _parse_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.strip().replace(",", "").replace("%", "")
    if cleaned in ("", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def fetch_csv(export_url: str) -> str:
    if not export_url:
        raise FinvizError(
            "No Finviz export URL configured. Set FINVIZ_EXPORT_URL_DISCOVERY "
            "(or FINVIZ_EXPORT_URL) in your .env -- see README for how to get it."
        )
    resp = requests.get(export_url, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        raise FinvizError(f"Finviz export request failed: HTTP {resp.status_code}")
    text = resp.text
    if "<html" in text[:200].lower():
        raise FinvizError(
            "Finviz returned an HTML page instead of CSV -- the export URL is likely "
            "expired or the auth token is invalid. Re-export from the Finviz Elite UI."
        )
    return text


def parse_rows(csv_text: str, field_map: FieldMap, now: datetime) -> list[TickerSnapshot]:
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise FinvizError("Finviz CSV response had no header row.")

    missing = [
        name
        for name in (field_map.ticker, field_map.price, field_map.volume)
        if name not in reader.fieldnames
    ]
    if missing:
        raise FinvizError(
            f"Finviz CSV is missing expected column(s) {missing}. "
            f"Actual headers were: {reader.fieldnames}. "
            "Run scripts/discover_finviz_columns.py and set the matching "
            "FINVIZ_FIELD_* env vars."
        )

    snapshots: list[TickerSnapshot] = []
    for row in reader:
        ticker = (row.get(field_map.ticker) or "").strip()
        if not ticker:
            continue
        price = _parse_number(row.get(field_map.price))
        volume = _parse_number(row.get(field_map.volume))
        if price is None or volume is None:
            continue
        snapshots.append(
            TickerSnapshot(
                ticker=ticker,
                price=price,
                volume=int(volume),
                change_pct=_parse_number(row.get(field_map.change_pct)),
                rel_volume=_parse_number(row.get(field_map.rel_volume)),
                timestamp=now,
            )
        )
    return snapshots


def fetch_snapshot(export_url: str, field_map: FieldMap, now: datetime) -> list[TickerSnapshot]:
    csv_text = fetch_csv(export_url)
    return parse_rows(csv_text, field_map, now)
