"""Tests for market_data.fundamentals — mocked yf.Ticker.info."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_data.fundamentals as fund  # noqa: E402
from market_data.fundamentals import fetch_fundamentals, format_market_cap  # noqa: E402


def _clear_cache():
    with fund._fundamentals_lock:
        fund._fundamentals_cache.clear()


def test_format_market_cap_units():
    assert format_market_cap(2_950_000_000_000) == "$2.95T"
    assert format_market_cap(48_200_000_000) == "$48.20B"
    assert format_market_cap(910_000_000) == "$910.00M"
    assert format_market_cap(None) == "—"
    assert format_market_cap(0) == "—"


def test_fetch_fundamentals_maps_info_fields():
    _clear_cache()
    info = {
        "shortName": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "marketCap": 3_000_000_000_000,
        "trailingPE": 31.5,
        "forwardPE": 28.1,
        "trailingEps": 6.42,
        "dividendYield": 0.0045,
        "beta": 1.21,
        "fiftyTwoWeekHigh": 250.0,
        "fiftyTwoWeekLow": 160.0,
    }
    ticker = MagicMock()
    ticker.info = info
    with patch.object(fund.yf, "Ticker", return_value=ticker):
        data = fetch_fundamentals("AAPL")
    assert data["name"] == "Apple Inc."
    assert data["sector"] == "Technology"
    assert data["market_cap"] == 3_000_000_000_000
    assert data["pe_ratio"] == 31.5
    assert data["forward_pe"] == 28.1
    assert data["beta"] == 1.21


def test_fetch_fundamentals_cached_one_hour():
    _clear_cache()
    ticker = MagicMock()
    ticker.info = {"shortName": "Test", "marketCap": 1_000_000}
    with patch.object(fund.yf, "Ticker", return_value=ticker) as mk:
        fetch_fundamentals("ZZZ")
        fetch_fundamentals("ZZZ")
    assert mk.call_count == 1  # second call served from cache


def test_fetch_fundamentals_failsilent_serves_stale():
    _clear_cache()
    good = MagicMock()
    good.info = {"shortName": "Good", "marketCap": 5}
    with patch.object(fund.yf, "Ticker", return_value=good):
        fetch_fundamentals("AAA")
    # expire the cache so a refetch is attempted
    fund._fundamentals_cache["AAA"]["ts"] = 0
    with patch.object(fund.yf, "Ticker", side_effect=RuntimeError("network")):
        data = fetch_fundamentals("AAA")
    assert data["name"] == "Good"  # stale payload served, no raise


def test_fetch_fundamentals_empty_symbol():
    assert fetch_fundamentals("") == {}
    assert fetch_fundamentals(None) == {}
