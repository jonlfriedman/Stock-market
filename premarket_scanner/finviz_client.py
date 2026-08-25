"""Finviz Elite screener export client.

Two distinct uses, per the build spec:

1. Universe screen (`build_universe_url`) -- run once each morning before
   the baseline window starts. Applies the actual stock-picking filters
   (`f=...`) to define the fixed ticker list for the session.
2. Live volume polling (`build_quote_url`) -- run every minute against that
   fixed ticker list (`t=...`), no `f=` filters, just raw current
   price/volume for exactly those tickers.

Finviz's export CSV column IDs aren't officially documented, so rather than
constructing requests from numeric column codes, both URL builders use the
account's Export API auth token and the CSV is parsed by its header row
text -- see config.FieldMap and scripts/discover_finviz_columns.py for
mapping headers once against a real account.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

import requests

from .config import FieldMap, Settings

REQUEST_TIMEOUT_SECONDS = 30
BASE_URL = "https://elite.finviz.com/export/screener"


class FinvizError(RuntimeError):
    pass


@dataclass
class TickerSnapshot:
    ticker: str
    price: float
    volume: int
    change_pct: float | None
    timestamp: datetime


def build_universe_url(settings: Settings) -> str:
    if not settings.finviz_api_key:
        raise FinvizError(
            "FINVIZ_API_KEY is not set. Set it as an environment variable "
            "(never paste it into chat) -- see README."
        )
    return (
        f"{BASE_URL}?v={settings.finviz_view}"
        f"&f={settings.universe_filter}"
        f"&ft={settings.finviz_ft}"
        f"&auth={settings.finviz_api_key}"
    )


def chunk_tickers(tickers: list[str], size: int) -> list[list[str]]:
    size = max(1, size)
    return [tickers[i : i + size] for i in range(0, len(tickers), size)]


def build_quote_url(settings: Settings, tickers: list[str]) -> str:
    if not settings.finviz_api_key:
        raise FinvizError(
            "FINVIZ_API_KEY is not set. Set it as an environment variable "
            "(never paste it into chat) -- see README."
        )
    ticker_param = quote(",".join(tickers), safe=",")
    return (
        f"{BASE_URL}?v={settings.finviz_view}"
        f"&t={ticker_param}"
        f"&ft={settings.finviz_ft}"
        f"&auth={settings.finviz_api_key}"
    )


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
    resp = requests.get(export_url, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        raise FinvizError(f"Finviz export request failed: HTTP {resp.status_code}")
    text = resp.text
    if "<html" in text[:200].lower():
        raise FinvizError(
            "Finviz returned an HTML page instead of CSV -- the auth token is "
            "likely invalid or expired. Re-check FINVIZ_API_KEY."
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
                timestamp=now,
            )
        )
    return snapshots


def fetch_snapshot(export_url: str, field_map: FieldMap, now: datetime) -> list[TickerSnapshot]:
    csv_text = fetch_csv(export_url)
    return parse_rows(csv_text, field_map, now)


def fetch_universe_snapshot(settings: Settings, now: datetime) -> list[TickerSnapshot]:
    """Run the universe screen (use #1) -- once per morning."""
    url = build_universe_url(settings)
    return fetch_snapshot(url, settings.field_map, now)


def fetch_quotes(settings: Settings, tickers: list[str], now: datetime) -> list[TickerSnapshot]:
    """Live volume poll (use #2) for a fixed ticker list -- once per minute.

    Chunked because Finviz export URLs have practical length limits and a
    single request for a large universe risks timing out.
    """
    if not tickers:
        return []
    by_ticker: dict[str, TickerSnapshot] = {}
    for chunk in chunk_tickers(tickers, settings.ticker_chunk_size):
        url = build_quote_url(settings, chunk)
        for snap in fetch_snapshot(url, settings.field_map, now):
            by_ticker[snap.ticker] = snap
    return list(by_ticker.values())
