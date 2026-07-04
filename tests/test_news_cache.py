"""Tests for market_data/news.py caching.

Covers the Review Finding at market_data/news.py:11 — unlike every other
market_data fetcher (TTL 10s to 1h), fetch_news hit yfinance on every call
with zero caching. Two Dash callbacks driven by the same "news-interval"
(headline strip + news content panel) fire back-to-back for the same
symbol each tick, doubling the network load for no reason.
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
        caches._news_cache["AAPL|8"]["ts"] = 0.0  # force expiry
        fetch_news("AAPL")

    assert _FakeTicker.call_count == 2


def test_fetch_news_cache_key_includes_max_items():
    _FakeTicker.call_count = 0
    with patch("market_data.news.yf.Ticker", _FakeTicker):
        fetch_news("AAPL", max_items=3)
        fetch_news("AAPL", max_items=5)

    assert _FakeTicker.call_count == 2
