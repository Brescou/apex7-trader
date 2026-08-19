"""Tests for market_data/news.py caching.

Covers the Review Finding at market_data/news.py — unlike every other
market_data fetcher (TTL 10s to 1h), fetch_news used to hit yfinance on
every call with zero caching. Concurrent REST callers for the same symbol
would each fire a network request.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from market_data import caches  # noqa: E402
from market_data.news import fetch_news  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_news_cache():
    caches._news_cache.clear()
    yield
    caches._news_cache.clear()


@pytest.fixture(autouse=True)
def _stub_finnhub():
    """Keep cache tests hermetic: a short yfinance stub must not hit Finnhub."""
    with patch("market_data.finnhub.fetch_finnhub_news", return_value=[]):
        yield


class _FakeTicker:
    call_count = 0

    def __init__(self, symbol):
        self.symbol = symbol
        _FakeTicker.call_count += 1

    @property
    def news(self):
        return [
            {
                "content": {
                    "title": f"{self.symbol} rallies on earnings beat",
                    "provider": {"displayName": "TestWire"},
                    "canonicalUrl": {"url": "https://example.com/a"},
                    "pubDate": "2026-06-11T12:00:00Z",
                }
            },
        ]


def test_fetch_news_hits_cache_on_second_call():
    _FakeTicker.call_count = 0
    with patch("market_data.news.yf.Ticker", _FakeTicker):
        first = fetch_news("AAPL")
        second = fetch_news("AAPL")

    assert first == second
    assert _FakeTicker.call_count == 1, "second call within the TTL must not hit yfinance again"


def test_fetch_news_cache_is_per_symbol():
    _FakeTicker.call_count = 0
    with patch("market_data.news.yf.Ticker", _FakeTicker):
        fetch_news("AAPL")
        fetch_news("MSFT")

    assert _FakeTicker.call_count == 2


def test_fetch_news_refetches_after_ttl_expires():
    _FakeTicker.call_count = 0
    with patch("market_data.news.yf.Ticker", _FakeTicker):
        fetch_news("AAPL")
        caches._news_cache["AAPL"]["ts"] = 0.0  # force expiry
        fetch_news("AAPL")

    assert _FakeTicker.call_count == 2


def test_fetch_news_different_limits_share_the_pool_cache():
    _FakeTicker.call_count = 0
    with patch("market_data.news.yf.Ticker", _FakeTicker):
        fetch_news("AAPL", max_items=3)
        fetch_news("AAPL", max_items=5)

    assert _FakeTicker.call_count == 1, "pagination slices a cached pool, it must not refetch"


class _EmptyTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    @property
    def news(self):
        return []


def test_fetch_news_falls_back_to_finnhub_when_yfinance_empty():
    fallback = [
        {
            "title": "Finnhub headline",
            "source": "Reuters",
            "age": "1h ago",
            "url": "https://example.com/n",
            "sentiment": "neutral",
            "_ts": 1765000000,
        }
    ]
    with patch("market_data.news.yf.Ticker", _EmptyTicker):
        with patch("market_data.finnhub.fetch_finnhub_news", return_value=fallback) as mock_fh:
            result = fetch_news("AAPL")

    assert result == [
        {k: v for k, v in fallback[0].items() if k != "_ts"},
    ]
    mock_fh.assert_called_once()


def test_fetch_news_fills_short_yfinance_from_finnhub():
    """Yahoo often returns ~10 headlines; Show more must pull Finnhub extras."""
    extras = [
        {
            "title": f"fh{i}",
            "source": "Reuters",
            "age": "1h ago",
            "url": f"https://finnhub.example/{i}",
            "sentiment": "neutral",
            "_ts": 1765001000 + i,
        }
        for i in range(12)
    ]

    class _TenTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def news(self):
            return [
                {
                    "title": f"yf{i}",
                    "publisher": "Yahoo",
                    "link": f"https://yahoo.example/{i}",
                    "providerPublishTime": 1765000000 + i,
                }
                for i in range(10)
            ]

    with patch("market_data.news.yf.Ticker", _TenTicker):
        with patch("market_data.finnhub.fetch_finnhub_news", return_value=extras):
            page = fetch_news("AAPL", max_items=8)
            more = fetch_news("AAPL", max_items=16)

    assert len(page) == 8
    assert len(more) == 16
    assert more[:8] == page
    assert any(it["title"].startswith("fh") for it in more[8:])


def test_fetch_news_skips_finnhub_when_yfinance_fills_the_pool():
    class _FullTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def news(self):
            return [
                {
                    "title": f"h{i}",
                    "publisher": "Wire",
                    "link": f"https://example.com/{i}",
                    "providerPublishTime": 1765000000 + i,
                }
                for i in range(40)
            ]

    with patch("market_data.news.yf.Ticker", _FullTicker):
        with patch("market_data.finnhub.fetch_finnhub_news") as mock_fh:
            result = fetch_news("AAPL", max_items=40)

    assert len(result) == 40
    mock_fh.assert_not_called()


def test_fetch_news_slices_cached_pool():
    class _ManyTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def news(self):
            return [
                {
                    "title": f"h{i}",
                    "publisher": "Wire",
                    "link": "https://example.com",
                    "providerPublishTime": 1765000000,
                }
                for i in range(20)
            ]

    with patch("market_data.news.yf.Ticker", _ManyTicker):
        page = fetch_news("AAPL", max_items=8)
        more = fetch_news("AAPL", max_items=16)

    assert len(page) == 8
    assert len(more) == 16
    assert more[:8] == page
