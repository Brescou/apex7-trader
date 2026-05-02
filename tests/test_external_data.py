"""Tests for FRED, CNN Fear & Greed, and earnings calendar helpers."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

import core.external_data as external_data
import market_data


@pytest.fixture(autouse=True)
def _reset_external_caches() -> None:
    """Avoid cross-test pollution from TTL caches in ``core.external_data``."""
    external_data._fred_series_cache.clear()
    external_data._macro_indicators_cache["data"] = None
    external_data._macro_indicators_cache["ts"] = 0.0
    external_data._fear_greed_cache["data"] = None
    external_data._fear_greed_cache["ts"] = 0.0
    market_data._earnings_cache["data"] = None
    market_data._earnings_cache["ts"] = 0.0
    market_data._earnings_cache["key"] = ""
    yield
    external_data._fred_series_cache.clear()
    external_data._macro_indicators_cache["data"] = None
    external_data._macro_indicators_cache["ts"] = 0.0
    external_data._fear_greed_cache["data"] = None
    external_data._fear_greed_cache["ts"] = 0.0
    market_data._earnings_cache["data"] = None
    market_data._earnings_cache["ts"] = 0.0
    market_data._earnings_cache["key"] = ""


def _httpx_client_context_mock(
    *,
    json_data: dict | None = None,
    get_side_effect: Exception | None = None,
) -> MagicMock:
    """Build a stand-in for ``with httpx.Client(...) as client: client.get(...)``."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    if json_data is not None:
        mock_response.json.return_value = json_data

    enter_client = MagicMock()
    if get_side_effect is not None:
        enter_client.get.side_effect = get_side_effect
    else:
        enter_client.get.return_value = mock_response

    ctx = MagicMock()
    ctx.__enter__.return_value = enter_client
    ctx.__exit__.return_value = None
    return ctx


def test_fred_returns_value() -> None:
    """``fetch_fred_latest`` returns a value/date dict when FRED responds OK."""
    payload = {
        "observations": [
            {"date": "2026-01-15", "value": "4.25"},
        ],
    }
    ctx = _httpx_client_context_mock(json_data=payload)
    with patch("core.external_data.httpx.Client", return_value=ctx):
        out = external_data.fetch_fred_latest("DGS10")

    assert out is not None
    assert isinstance(out["value"], float)
    assert out["value"] == 4.25
    assert isinstance(out["date"], str)
    assert out["date"] == "2026-01-15"


def test_fred_fail_silent() -> None:
    """HTTP failure on FRED yields ``None`` without raising."""
    ctx = _httpx_client_context_mock(get_side_effect=httpx.HTTPError("boom"))
    with patch("core.external_data.httpx.Client", return_value=ctx):
        out = external_data.fetch_fred_latest("DGS10")
    assert out is None


def test_fear_greed_parses() -> None:
    """CNN payload maps to ``score`` (int) and ``label`` (str)."""
    payload = {
        "fear_and_greed": {
            "score": 42.7,
            "rating": "Fear",
        },
    }
    ctx = _httpx_client_context_mock(json_data=payload)
    with patch("core.external_data.httpx.Client", return_value=ctx):
        out = external_data.fetch_fear_greed()

    assert out is not None
    assert isinstance(out["score"], int)
    assert out["score"] == 43
    assert isinstance(out["label"], str)
    assert out["label"] == "Fear"


def test_fear_greed_fail_silent() -> None:
    """Fear & Greed HTTP/runtime errors yield ``None``."""
    ctx = _httpx_client_context_mock(get_side_effect=RuntimeError("offline"))
    with patch("core.external_data.httpx.Client", return_value=ctx):
        out = external_data.fetch_fear_greed()
    assert out is None


def test_earnings_calendar() -> None:
    """``fetch_earnings_calendar`` exposes ``earnings_date`` and ``days_until``."""
    today = date.today()
    ed = today + timedelta(days=8)

    class FakeTicker:
        def __init__(self, _symbol: str) -> None:
            self.calendar = {"Earnings Date": [ed]}

    with patch("market_data.yf.Ticker", FakeTicker):
        out = market_data.fetch_earnings_calendar(["AAPL"])

    assert out["AAPL"] is not None
    assert out["AAPL"]["earnings_date"] == str(ed)
    assert out["AAPL"]["days_until"] == 8


def test_is_earnings_week_true() -> None:
    """Earnings in three days falls inside the 5-day window."""
    today = date.today()
    ed = today + timedelta(days=3)

    class FakeTicker:
        def __init__(self, _symbol: str) -> None:
            self.calendar = {"Earnings Date": [ed]}

    with patch("market_data.yf.Ticker", FakeTicker):
        assert market_data.is_earnings_week("AAPL") is True


def test_is_earnings_week_false() -> None:
    """Earnings in 30 days is outside the earnings-week window."""
    today = date.today()
    ed = today + timedelta(days=30)

    class FakeTicker:
        def __init__(self, _symbol: str) -> None:
            self.calendar = {"Earnings Date": [ed]}

    with patch("market_data.yf.Ticker", FakeTicker):
        assert market_data.is_earnings_week("AAPL") is False


def test_earnings_fail_silent() -> None:
    """yfinance errors map to ``None`` per symbol."""

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("yfinance unavailable")

    with patch("market_data.yf.Ticker", side_effect=boom):
        out = market_data.fetch_earnings_calendar(["AAPL"])

    assert out == {"AAPL": None}
