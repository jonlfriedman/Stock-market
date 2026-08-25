from datetime import datetime

import pytest

from premarket_scanner.config import FieldMap, Settings
from premarket_scanner.finviz_client import (
    FinvizError,
    build_quote_url,
    build_universe_url,
    chunk_tickers,
    parse_rows,
)

SAMPLE_CSV = (
    "Ticker,Company,Price,Change,Volume\n"
    "AAPL,Apple Inc,225.31,2.15%,45123456\n"
    "XYZ,Small Cap Co,3.20,-1.10%,987654\n"
    "BAD,Bad Row,,,\n"
)


def test_parse_rows_basic():
    now = datetime(2026, 8, 21, 6, 45)
    rows = parse_rows(SAMPLE_CSV, FieldMap(), now)
    assert len(rows) == 2  # BAD row dropped: missing price/volume

    aapl = rows[0]
    assert aapl.ticker == "AAPL"
    assert aapl.price == 225.31
    assert aapl.volume == 45123456
    assert aapl.change_pct == 2.15
    assert aapl.timestamp == now


def test_parse_rows_missing_expected_column_raises():
    bad_csv = "Symbol,Cost\nAAPL,225.31\n"
    with pytest.raises(FinvizError):
        parse_rows(bad_csv, FieldMap(), datetime.now())


def test_parse_rows_custom_field_map():
    csv_text = "Sym,Last,Vol\nMSFT,410.5,1200000\n"
    fm = FieldMap(ticker="Sym", price="Last", volume="Vol", change_pct="Change")
    rows = parse_rows(csv_text, fm, datetime.now())
    assert rows[0].ticker == "MSFT"
    assert rows[0].price == 410.5
    assert rows[0].volume == 1200000
    assert rows[0].change_pct is None


def test_build_universe_url_includes_filters_and_auth():
    settings = Settings(finviz_api_key="SECRET123", universe_filter="ind_stocksonly,sh_price_1to10")
    url = build_universe_url(settings)
    assert url.startswith("https://elite.finviz.com/export/screener?")
    assert "f=ind_stocksonly,sh_price_1to10" in url
    assert "auth=SECRET123" in url
    assert "v=111" in url
    assert "ft=4" in url


def test_build_universe_url_requires_api_key():
    settings = Settings(finviz_api_key="")
    with pytest.raises(FinvizError):
        build_universe_url(settings)


def test_build_quote_url_uses_ticker_list_not_filters():
    settings = Settings(finviz_api_key="SECRET123")
    url = build_quote_url(settings, ["AAPL", "MSFT", "XYZ"])
    assert "t=AAPL,MSFT,XYZ" in url
    assert "f=" not in url
    assert "auth=SECRET123" in url


def test_chunk_tickers_splits_by_size():
    tickers = [f"T{i}" for i in range(250)]
    chunks = chunk_tickers(tickers, 100)
    assert len(chunks) == 3
    assert len(chunks[0]) == 100
    assert len(chunks[2]) == 50
    assert sum(len(c) for c in chunks) == 250


def test_chunk_tickers_empty():
    assert chunk_tickers([], 100) == []
