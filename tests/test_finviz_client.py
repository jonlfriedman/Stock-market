from datetime import datetime

import pytest

from premarket_scanner.config import FieldMap
from premarket_scanner.finviz_client import FinvizError, parse_rows

SAMPLE_CSV = (
    "Ticker,Company,Price,Change,Volume,Relative Volume\n"
    "AAPL,Apple Inc,225.31,2.15%,45123456,3.42\n"
    "XYZ,Small Cap Co,3.20,-1.10%,987654,1.85\n"
    "BAD,Bad Row,,,,\n"
)


def test_parse_rows_basic():
    now = datetime(2026, 8, 21, 4, 5)
    rows = parse_rows(SAMPLE_CSV, FieldMap(), now)
    assert len(rows) == 2  # BAD row dropped: missing price/volume

    aapl = rows[0]
    assert aapl.ticker == "AAPL"
    assert aapl.price == 225.31
    assert aapl.volume == 45123456
    assert aapl.change_pct == 2.15
    assert aapl.rel_volume == 3.42
    assert aapl.timestamp == now


def test_parse_rows_missing_expected_column_raises():
    bad_csv = "Symbol,Cost\nAAPL,225.31\n"
    with pytest.raises(FinvizError):
        parse_rows(bad_csv, FieldMap(), datetime.now())


def test_parse_rows_custom_field_map():
    csv_text = "Sym,Last,Vol\nMSFT,410.5,1200000\n"
    fm = FieldMap(ticker="Sym", price="Last", volume="Vol", change_pct="Change", rel_volume="Rel Volume")
    rows = parse_rows(csv_text, fm, datetime.now())
    assert rows[0].ticker == "MSFT"
    assert rows[0].price == 410.5
    assert rows[0].volume == 1200000
    assert rows[0].change_pct is None
