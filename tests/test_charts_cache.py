"""Tests for market_data/charts.py lock-release + circuit-breaker wiring.

Covers the Review Finding at market_data/charts.py:25 — fetch_sparkline /
fetch_comparison / fetch_ohlcv held their global lock across the whole
yf.Ticker(...).history() network call, never consulted yf_circuit_open(),
and never called record_yf_failure() on error — so during a yfinance
outage every tick kept retrying (serialized behind one lock) instead of
serving the still-valid cache like quotes.py/macro.py already do.
"""

import os
import sys
import threading
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data import caches, charts  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_charts_state():
    caches._sparkline_cache.clear()
    caches._comparison_cache.clear()
    caches._ohlcv_cache.clear()
    caches._yf_circuit["failures"] = 0
    caches._yf_circuit["paused_until"] = 0.0
    yield
    caches._sparkline_cache.clear()
    caches._comparison_cache.clear()
    caches._ohlcv_cache.clear()
    caches._yf_circuit["failures"] = 0
    caches._yf_circuit["paused_until"] = 0.0


def _fake_history(n=5):
    idx = pd.date_range("2026-01-02", periods=n, freq="D")
    close = np.linspace(100.0, 110.0, n)
    return pd.DataFrame(
        {
            "Open": close * 0.999,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(n, 2_000_000),
        },
        index=idx,
    )


class _FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period="5d", interval="1d", **_kwargs):
        return _fake_history()


# ── Circuit breaker consulted before attempting the network call ──────────


def test_sparkline_serves_stale_when_circuit_open():
    caches._sparkline_cache["AAPL"] = {
        "data": [{"time": "10:00", "price": 1.0, "open": 1.0}],
        "ts": 0.0,
    }
    with patch.object(charts, "yf_circuit_open", return_value=True):
        with patch("market_data.charts.yf.Ticker") as ticker:
            out = charts.fetch_sparkline("AAPL")
    ticker.assert_not_called()
    assert out == [{"time": "10:00", "price": 1.0, "open": 1.0}]


def test_comparison_serves_stale_when_circuit_open():
    caches._comparison_cache["AAPL|1mo"] = {
        "data": {"AAPL": [{"date": "x", "value": 100.0}]},
        "ts": 0.0,
    }
    with patch.object(charts, "yf_circuit_open", return_value=True):
        with patch("market_data.charts.yf.Ticker") as ticker:
            out = charts.fetch_comparison(["AAPL"], period="1mo")
    ticker.assert_not_called()
    assert out == {"AAPL": [{"date": "x", "value": 100.0}]}


def test_ohlcv_serves_stale_when_circuit_open():
    caches._ohlcv_cache["AAPL|1mo"] = {"data": [{"date": "x", "close": 1.0}], "ts": 0.0}
    with patch.object(charts, "yf_circuit_open", return_value=True):
        with patch("market_data.charts.yf.Ticker") as ticker:
            out = charts.fetch_ohlcv("AAPL", period="1mo")
    ticker.assert_not_called()
    assert out == [{"date": "x", "close": 1.0}]


# ── record_yf_failure/success wired in ─────────────────────────────────────


def test_sparkline_failure_trips_the_shared_circuit_breaker():
    """3 distinct symbols each failing once must open the shared breaker —
    this only works if fetch_sparkline actually calls record_yf_failure().
    Uses 3 different symbols (not repeated calls for one) because a failed
    fetch is itself cached for the TTL, same as a good one — a single
    symbol failing once wouldn't hit the network again within this test.
    """

    def _boom(*_a, **_k):
        raise RuntimeError("yfinance down")

    with patch("market_data.charts.yf.Ticker", side_effect=_boom):
        for sym in ("AAPL", "MSFT", "GOOGL"):
            charts.fetch_sparkline(sym)

    assert caches.yf_circuit_open() is True


def test_sparkline_success_resets_the_circuit_breaker():
    caches._yf_circuit["failures"] = 2
    with patch("market_data.charts.yf.Ticker", _FakeTicker):
        charts.fetch_sparkline("AAPL")
    assert caches._yf_circuit["failures"] == 0


# ── Lock released during network I/O ────────────────────────────────────────


def test_fetch_sparkline_releases_lock_during_network_io():
    entered = threading.Event()
    release = threading.Event()

    class _BlockingTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="5d", interval="1d", **_kwargs):
            entered.set()
            release.wait(timeout=2.0)
            return _fake_history()

    holder: dict = {}

    def _run():
        with patch("market_data.charts.yf.Ticker", _BlockingTicker):
            holder["result"] = charts.fetch_sparkline("AAPL")

    worker = threading.Thread(target=_run)
    worker.start()
    try:
        assert entered.wait(timeout=2.0), "fetch never reached the network call"
        acquired = caches._sparkline_lock.acquire(timeout=1.0)
        try:
            assert acquired, "_sparkline_lock was held during the network I/O call"
        finally:
            if acquired:
                caches._sparkline_lock.release()
    finally:
        release.set()
        worker.join(timeout=5.0)

    assert not worker.is_alive()
    assert holder["result"] and holder["result"][0]["price"] == 100.0


def test_fetch_comparison_releases_lock_during_network_io():
    entered = threading.Event()
    release = threading.Event()

    class _BlockingTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="1mo", interval="1d", **_kwargs):
            entered.set()
            release.wait(timeout=2.0)
            return _fake_history()

    def _run():
        with patch("market_data.charts.yf.Ticker", _BlockingTicker):
            charts.fetch_comparison(["AAPL"], period="1mo")

    worker = threading.Thread(target=_run)
    worker.start()
    try:
        assert entered.wait(timeout=2.0), "fetch never reached the network call"
        acquired = caches._comparison_lock.acquire(timeout=1.0)
        try:
            assert acquired, "_comparison_lock was held during the network I/O call"
        finally:
            if acquired:
                caches._comparison_lock.release()
    finally:
        release.set()
        worker.join(timeout=5.0)
    assert not worker.is_alive()


def test_fetch_ohlcv_releases_lock_during_network_io():
    entered = threading.Event()
    release = threading.Event()

    class _BlockingTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="1mo", interval="1d", **_kwargs):
            entered.set()
            release.wait(timeout=2.0)
            return _fake_history()

    def _run():
        with patch("market_data.charts.yf.Ticker", _BlockingTicker):
            charts.fetch_ohlcv("AAPL", period="1mo")

    worker = threading.Thread(target=_run)
    worker.start()
    try:
        assert entered.wait(timeout=2.0), "fetch never reached the network call"
        acquired = caches._ohlcv_lock.acquire(timeout=1.0)
        try:
            assert acquired, "_ohlcv_lock was held during the network I/O call"
        finally:
            if acquired:
                caches._ohlcv_lock.release()
    finally:
        release.set()
        worker.join(timeout=5.0)
    assert not worker.is_alive()
