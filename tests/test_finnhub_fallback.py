"""Tests for the Finnhub fallback data provider."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_data.finnhub as fh
from market_data.finnhub import (
    _is_plain_ticker,
    fetch_finnhub_news,
    fetch_finnhub_quote,
    fetch_finnhub_quotes,
)


@pytest.fixture(autouse=True)
def clear_finnhub_cache():
    fh._fh_cache.clear()
    fh._fh_news_cache.clear()
    fh._missing_key_warned = False
    yield
    fh._fh_cache.clear()
    fh._fh_news_cache.clear()
    fh._missing_key_warned = False


# ── _is_plain_ticker ──────────────────────────────────────────────────────────


def test_plain_ticker_accepted():
    assert _is_plain_ticker("AAPL")
    assert _is_plain_ticker("SPY")
    assert _is_plain_ticker("MSFT")


def test_special_chars_rejected():
    assert not _is_plain_ticker("^VIX")
    assert not _is_plain_ticker("DX-Y.NYB")
    assert not _is_plain_ticker("BTC-USD")
    assert not _is_plain_ticker("")


def test_lowercase_rejected():
    assert not _is_plain_ticker("aapl")


# ── fetch_finnhub_quote ───────────────────────────────────────────────────────

_GOOD_PAYLOAD = {"c": 150.5, "d": 2.1, "dp": 1.41, "h": 152.0, "l": 148.3, "pc": 148.4}


def test_quote_parses_payload():
    with patch.object(fh, "_api_key", return_value="test-key"):
        with patch("market_data.finnhub.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.json.return_value = _GOOD_PAYLOAD
            mock_resp.raise_for_status.return_value = None
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

            q = fetch_finnhub_quote("AAPL")

    assert q is not None
    assert q["price"] == 150.5
    assert q["change_abs"] == 2.1
    assert q["change_pct"] == 1.41
    assert q["prev_close"] == 148.4


def test_quote_skips_special_symbols():
    assert fetch_finnhub_quote("^VIX") is None
    assert fetch_finnhub_quote("DX-Y.NYB") is None


def test_quote_returns_none_on_zero_price():
    with patch.object(fh, "_api_key", return_value="test-key"):
        with patch("market_data.finnhub.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"c": 0, "d": 0, "dp": 0}
            mock_resp.raise_for_status.return_value = None
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            q = fetch_finnhub_quote("AAPL")
    assert q is None


def test_quote_returns_none_on_network_error():
    with patch("market_data.finnhub.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.get.side_effect = Exception("timeout")
        q = fetch_finnhub_quote("MSFT")
    assert q is None


def test_quote_cached_second_call_no_http():
    with patch.object(fh, "_api_key", return_value="test-key"):
        with patch("market_data.finnhub.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.json.return_value = _GOOD_PAYLOAD
            mock_resp.raise_for_status.return_value = None
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

            fetch_finnhub_quote("AAPL")
            fetch_finnhub_quote("AAPL")  # second call — must hit cache

    assert mock_client_cls.call_count == 1


# ── Missing API key: fallback must not silently no-op ────────────────────────


def test_quote_skips_network_call_without_api_key():
    """Without FINNHUB_API_KEY, Finnhub's real /quote endpoint 401s on every
    request — attempting it is pure wasted latency. The fix short-circuits
    before the network call instead of hitting it and swallowing a 401.
    """
    with patch.object(fh, "_api_key", return_value=""):
        with patch("market_data.finnhub.httpx.Client") as mock_client_cls:
            q = fetch_finnhub_quote("AAPL")
    mock_client_cls.assert_not_called()
    assert q is None


def test_missing_api_key_warns_once_per_process():
    """A missing key must be surfaced above debug level (Review Finding: the
    fallback was a silent no-op with no operator-visible signal) — but only
    once, since this path is only exercised while yfinance is already down
    and would otherwise flood the logs exactly when they matter most.
    """
    fh._missing_key_warned = False
    with patch.object(fh, "_api_key", return_value=""):
        with patch("market_data.finnhub.httpx.Client"):
            with patch.object(fh.logger, "warning") as mock_warn:
                fetch_finnhub_quote("AAPL")
                fh._fh_cache.clear()  # force past the per-symbol TTL cache
                fetch_finnhub_quote("MSFT")
    assert mock_warn.call_count == 1
    fh._missing_key_warned = False


# ── fetch_finnhub_quotes batch ───────────────────────────────────────────────


def test_batch_only_returns_resolved():
    results = {"AAPL": _GOOD_PAYLOAD, "MSFT": _GOOD_PAYLOAD}

    def _fake_quote(sym):
        return (
            {
                "price": results[sym]["c"],
                "change_abs": results[sym]["d"],
                "change_pct": results[sym]["dp"],
                "high": results[sym]["h"],
                "low": results[sym]["l"],
                "prev_close": results[sym]["pc"],
            }
            if sym in results
            else None
        )

    with patch.object(fh, "fetch_finnhub_quote", side_effect=_fake_quote):
        out = fetch_finnhub_quotes(["AAPL", "MSFT", "^VIX"])

    assert set(out.keys()) == {"AAPL", "MSFT"}
    assert "^VIX" not in out


# ── Integration: quotes.py fallback ──────────────────────────────────────────


def test_watchlist_uses_finnhub_when_circuit_open():
    import market_data.quotes as qmod
    from market_data.caches import _watchlist_cache

    _watchlist_cache["data"] = {
        "AAPL": {
            "price": 140.0,
            "change_pct": 0.0,
            "change_abs": 0.0,
            "volume": 1000,
            "high_52w": 180.0,
            "low_52w": 120.0,
            "rsi_14": 55.0,
            "above_ma20": True,
            "macd_hist": 0.1,
            "bb_pos": "mid",
        }
    }
    _watchlist_cache["key"] = "AAPL"
    _watchlist_cache["ts"] = 0.0  # expired

    fresh_quote = {
        "AAPL": {
            "price": 152.0,
            "change_abs": 3.0,
            "change_pct": 2.01,
            "high": 153.0,
            "low": 149.0,
            "prev_close": 149.0,
        }
    }
    with patch("market_data.quotes.yf_circuit_open", return_value=True):
        with patch("market_data.quotes.fetch_finnhub_quotes", return_value=fresh_quote):
            result = qmod.fetch_watchlist_prices(["AAPL"])

    assert result["AAPL"]["price"] == 152.0
    assert result["AAPL"]["change_pct"] == 2.01
    # RSI and 52w from stale cache
    assert result["AAPL"]["rsi_14"] == 55.0
    assert result["AAPL"]["high_52w"] == 180.0


def test_watchlist_falls_back_to_stale_when_finnhub_empty():
    import market_data.quotes as qmod
    from market_data.caches import _watchlist_cache

    stale = {
        "AAPL": {
            "price": 140.0,
            "change_pct": 0.0,
            "change_abs": 0.0,
            "volume": 0,
            "high_52w": None,
            "low_52w": None,
            "rsi_14": 50.0,
            "above_ma20": False,
            "macd_hist": 0.0,
            "bb_pos": "mid",
        }
    }
    _watchlist_cache["data"] = stale
    _watchlist_cache["key"] = "AAPL"
    _watchlist_cache["ts"] = 0.0

    with patch("market_data.quotes.yf_circuit_open", return_value=True):
        with patch("market_data.quotes.fetch_finnhub_quotes", return_value={}):
            result = qmod.fetch_watchlist_prices(["AAPL"])

    assert result == stale


# ── Integration: macro.py fallback ───────────────────────────────────────────


def test_macro_refreshes_plain_tickers_via_finnhub():
    import market_data.macro as mmod
    from market_data.caches import _macro_cache

    _macro_cache["data"] = {
        "VIX": {"price": 20.0, "change_pct": 0.0, "direction": "flat"},
        "SPY": {"price": 500.0, "change_pct": 0.0, "direction": "flat"},
        "DXY": {"price": 104.0, "change_pct": 0.0, "direction": "flat"},
    }
    _macro_cache["ts"] = 0.0

    def _fake_fh_quote(sym):
        if sym == "SPY":
            return {
                "price": 510.0,
                "change_pct": 2.0,
                "change_abs": 10.0,
                "high": 511.0,
                "low": 508.0,
                "prev_close": 500.0,
            }
        return None  # ^VIX, DX-Y.NYB → skipped

    with patch("market_data.macro.yf_circuit_open", return_value=True):
        with patch("market_data.macro.fetch_finnhub_quote", side_effect=_fake_fh_quote):
            result = mmod.fetch_macro()

    # SPY refreshed
    assert result["SPY"]["price"] == 510.0
    assert result["SPY"]["direction"] == "up"
    # VIX/DXY kept from stale
    assert result["VIX"]["price"] == 20.0
    assert result["DXY"]["price"] == 104.0


# ── fetch_finnhub_news ────────────────────────────────────────────────────────


_NEWS_PAYLOAD = [
    {
        "headline": "Apple beats estimates",
        "source": "Reuters",
        "url": "https://example.com/r",
        "datetime": 1765000000,
    },
    {
        "headline": "",
        "source": "SkipMe",
        "url": "https://example.com/x",
        "datetime": 1,
    },
]


def test_news_parses_payload():
    with patch.object(fh, "_api_key", return_value="test-key"):
        with patch("market_data.finnhub.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.json.return_value = _NEWS_PAYLOAD
            mock_resp.raise_for_status.return_value = None
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            items = fetch_finnhub_news("AAPL")

    assert len(items) == 1
    assert items[0]["title"] == "Apple beats estimates"
    assert items[0]["source"] == "Reuters"
    assert items[0]["url"] == "https://example.com/r"
    assert items[0]["sentiment"] in ("positive", "negative", "neutral")
    assert "age" in items[0]


def test_news_skips_special_symbols():
    assert fetch_finnhub_news("^VIX") == []
    assert fetch_finnhub_news("DX-Y.NYB") == []


def test_news_skips_network_without_api_key():
    with patch.object(fh, "_api_key", return_value=""):
        with patch("market_data.finnhub.httpx.Client") as mock_client_cls:
            items = fetch_finnhub_news("AAPL")
    mock_client_cls.assert_not_called()
    assert items == []


def test_news_cached_second_call_no_http():
    with patch.object(fh, "_api_key", return_value="test-key"):
        with patch("market_data.finnhub.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.json.return_value = _NEWS_PAYLOAD
            mock_resp.raise_for_status.return_value = None
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            fetch_finnhub_news("AAPL")
            fetch_finnhub_news("AAPL")
    assert mock_client_cls.call_count == 1


def test_news_returns_empty_on_network_error():
    with patch.object(fh, "_api_key", return_value="test-key"):
        with patch("market_data.finnhub.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = Exception(
                "timeout"
            )
            items = fetch_finnhub_news("MSFT")
    assert items == []
