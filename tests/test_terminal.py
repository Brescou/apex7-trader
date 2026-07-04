"""Terminal/market_data tests for APEX-7.

Run with:  uv run pytest tests/test_terminal.py -v
Legacy:    uv run python tests/test_terminal.py
"""

import os
import sys
import traceback
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────


def _reset_macro_cache() -> None:
    from market_data import caches

    caches._macro_cache["data"] = None
    caches._macro_cache["ts"] = 0.0
    caches.record_yf_success()


def _reset_watchlist_cache() -> None:
    from market_data import caches

    caches._watchlist_cache["data"] = None
    caches._watchlist_cache["ts"] = 0.0
    caches._watchlist_cache["key"] = ""
    caches.record_yf_success()


def _reset_sector_cache() -> None:
    from market_data import caches

    caches._sector_perf_cache["data"] = None
    caches._sector_perf_cache["ts"] = 0.0
    caches._sector_perf_cache["key"] = ""


def _reset_corr_cache() -> None:
    from market_data import caches

    caches._corr_matrix_cache["data"] = None
    caches._corr_matrix_cache["ts"] = 0.0
    caches._corr_matrix_cache["key"] = ""


class _FakeTicker:
    """Offline yfinance stand-in — deterministic rising closes + canned news.

    Keeps ``test_fetch_macro`` / ``test_fetch_watchlist_prices`` /
    ``test_fetch_news`` hermetic (no network, no rate-limit flakiness).
    """

    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period="5d", interval="1d", **_kwargs):
        n = 260 if period == "1y" else 5
        idx = pd.date_range("2026-01-02", periods=n, freq="D")
        close = np.linspace(100.0, 110.0, n)
        volume = np.full(n, 2_000_000)
        high = close * 1.01
        low = close * 0.99
        return pd.DataFrame(
            {"Open": close * 0.999, "High": high, "Low": low, "Close": close, "Volume": volume},
            index=idx,
        )

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
            {
                "title": f"{self.symbol} slides after downgrade",
                "publisher": "TestWire",
                "link": "https://example.com/b",
                "providerPublishTime": 1765000000,
            },
        ]


# ─────────────────────────────────────────────────────────────────────────────


def test_fetch_macro():
    import market_data as md
    from market_data import fetch_macro

    _reset_macro_cache()
    with patch.object(md.yf, "Ticker", _FakeTicker):
        result = fetch_macro()
    assert isinstance(result, dict), f"fetch_macro must return dict, got {type(result)}"
    assert len(result) > 0, "fetch_macro returned empty dict"
    if "updated_at" in result:
        assert isinstance(result["updated_at"], str)
    for key, val in result.items():
        if key == "updated_at":
            continue
        assert "price" in val, f"Missing 'price' in macro entry {key}"
        assert "change_pct" in val, f"Missing 'change_pct' in macro entry {key}"
        assert "direction" in val, f"Missing 'direction' in macro entry {key}"
        assert val["direction"] in ("up", "down", "flat"), f"Invalid direction: {val['direction']}"
        # Rising fake closes (107.5 → 110.0) must classify as "up".
        assert val["price"] == 110.0, f"Unexpected price for {key}: {val['price']}"
        assert val["direction"] == "up", f"Expected 'up' for {key}, got {val['direction']}"


def test_fetch_watchlist_prices():
    import market_data as md
    from market_data import fetch_watchlist_prices

    symbols = ["AAPL", "MSFT"]
    _reset_watchlist_cache()
    with patch.object(md.yf, "Ticker", _FakeTicker):
        result = fetch_watchlist_prices(symbols)
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    for sym in symbols:
        assert sym in result, f"Missing symbol {sym} in result"
        entry = result[sym]
        required = [
            "price",
            "change_pct",
            "change_abs",
            "volume",
            "high_52w",
            "low_52w",
            "rsi_14",
            "above_ma20",
        ]
        for k in required:
            assert k in entry, f"Missing key '{k}' in watchlist entry for {sym}"
        assert isinstance(entry["above_ma20"], bool), f"above_ma20 must be bool for {sym}"
        assert isinstance(entry["rsi_14"], (float, int, type(None))), f"rsi_14 type error for {sym}"
        # Monotonically rising fake closes → last price 110.0, above the MA20.
        assert entry["price"] == 110.0, f"Unexpected price for {sym}: {entry['price']}"
        assert entry["above_ma20"] is True, f"Expected above_ma20=True for {sym}"


def test_fetch_watchlist_prices_releases_lock_during_network_io():
    """``fetch_watchlist_prices`` must not hold ``_watchlist_lock`` for the
    whole batch of sequential yfinance calls — otherwise every other caller
    (check-alerts callback, screener, API routes) freezes behind it for as
    long as the network fetch takes (Review Finding, market_data/quotes.py
    line 57). Verified by blocking inside a fake ``.history()`` call and
    confirming the lock can still be acquired from another thread while the
    fetch is in flight.
    """
    import threading
    import time as time_mod

    import market_data as md
    from market_data import caches, fetch_watchlist_prices

    _reset_watchlist_cache()

    entered_history = threading.Event()
    release_history = threading.Event()

    class _BlockingTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="5d", interval="1d", **_kwargs):
            entered_history.set()
            release_history.wait(timeout=2.0)
            n = 260 if period == "1y" else 5
            idx = pd.date_range("2026-01-02", periods=n, freq="D")
            close = np.linspace(100.0, 110.0, n)
            volume = np.full(n, 2_000_000)
            return pd.DataFrame(
                {
                    "Open": close * 0.999,
                    "High": close * 1.01,
                    "Low": close * 0.99,
                    "Close": close,
                    "Volume": volume,
                },
                index=idx,
            )

    result_holder: dict = {}

    def _run():
        with patch.object(md.yf, "Ticker", _BlockingTicker):
            result_holder["result"] = fetch_watchlist_prices(["AAPL"])

    worker = threading.Thread(target=_run)
    worker.start()
    try:
        assert entered_history.wait(timeout=2.0), "fetch never reached the network call"
        # The fetch is now blocked *inside* the fake network call. If the
        # lock were held for the whole loop (the pre-fix behaviour), this
        # acquire would time out.
        acquired = caches._watchlist_lock.acquire(timeout=1.0)
        try:
            assert acquired, "_watchlist_lock was held during the network I/O call"
        finally:
            if acquired:
                caches._watchlist_lock.release()
    finally:
        release_history.set()
        worker.join(timeout=5.0)

    assert not worker.is_alive()
    assert result_holder.get("result", {}).get("AAPL", {}).get("price") == 110.0
    time_mod.sleep(0)  # let the worker's cache write settle before other tests run


def test_fetch_news():
    import market_data as md
    from market_data import fetch_news

    with patch.object(md.yf, "Ticker", _FakeTicker):
        result = fetch_news("AAPL")
    assert isinstance(result, list), f"fetch_news must return list, got {type(result)}"
    assert len(result) == 2, f"Expected 2 fake news items, got {len(result)}"
    for item in result:
        assert "title" in item, f"News item missing 'title': {item}"
        assert "source" in item, f"News item missing 'source': {item}"
        assert "age" in item, f"News item missing 'age': {item}"
        assert "url" in item, f"News item missing 'url': {item}"
        assert "sentiment" in item, f"News item missing 'sentiment': {item}"
        assert item["sentiment"] in (
            "positive",
            "negative",
            "neutral",
        ), f"Invalid sentiment: {item['sentiment']}"
    # Modern (content dict) and legacy (flat) yfinance news shapes both parse.
    assert result[0]["title"] == "AAPL rallies on earnings beat"
    assert result[0]["source"] == "TestWire"
    assert result[0]["url"] == "https://example.com/a"
    assert result[1]["title"] == "AAPL slides after downgrade"


def test_run_screener():
    """Hermetic — mocks yfinance via ``_FakeTicker`` (Review Finding: this
    test previously hit the real network with no mocks and no assertions
    that would fail on empty/missing data, so a rate-limited or offline run
    passed without ever exercising the filtering logic).
    """
    import market_data as md
    from market_data import run_screener

    symbols = ["AAPL", "MSFT", "GOOGL"]
    _reset_watchlist_cache()
    with patch.object(md.yf, "Ticker", _FakeTicker):
        result = run_screener(symbols, {})
        result2 = run_screener(symbols, {"rsi_min": 0})
        result3 = run_screener(symbols, {"rsi_min": 150})

    assert isinstance(result, list) and len(result) == 3
    # _FakeTicker's monotonically rising closes → RSI saturates at 100.
    for entry in result:
        assert entry["symbol"] in symbols
        assert entry["rsi_14"] == 100.0
        assert entry["price"] == 110.0

    assert isinstance(result2, list) and len(result2) == 3

    assert result3 == [], f"Expected empty list for impossible filter, got {result3}"


def test_fetch_sparkline():
    """Hermetic — mocks yfinance via ``_FakeTicker`` (Review Finding: was
    hitting the real network with a self-neutering ``if len(result) == 0:
    return``, so a rate-limited/offline run silently skipped every
    assertion below it).
    """
    import market_data as md
    from market_data import fetch_sparkline

    from market_data import caches

    caches._sparkline_cache.pop("AAPL", None)

    with patch.object(md.yf, "Ticker", _FakeTicker):
        result = fetch_sparkline("AAPL")

    assert isinstance(result, list) and len(result) == 5
    first = result[0]
    assert first["price"] == 100.0
    assert first["open"] == pytest.approx(100.0 * 0.999)
    assert result[-1]["price"] == 110.0
    for row in result:
        assert isinstance(row["price"], (int, float))
        assert "time" in row


def test_fetch_comparison():
    """Hermetic — mocks yfinance via ``_FakeTicker`` (Review Finding: was
    hitting the real network with a self-neutering ``if not result:
    return``, so a rate-limited/offline run silently skipped every
    assertion below it).
    """
    import market_data as md
    from market_data import fetch_comparison

    from market_data import caches

    caches._comparison_cache.clear()

    with patch.object(md.yf, "Ticker", _FakeTicker):
        result = fetch_comparison(["AAPL", "MSFT"], period="1mo")

    assert isinstance(result, dict)
    for sym in ["AAPL", "MSFT"]:
        assert sym in result, f"Missing symbol {sym} in comparison result"
        series = result[sym]
        assert len(series) == 5
        assert series[0]["value"] == 100.0, "first point must normalize to 100.0"
        assert series[-1]["value"] == pytest.approx(110.0)


def test_cache_behavior():
    """Repeated calls within the TTL must return the cached result without
    re-hitting yfinance (Review Finding: the pre-fix version hit the real
    network with no mocks; two consecutive real calls trivially "matched"
    whenever both failed identically, so it never actually verified caching).
    """
    from market_data import fetch_watchlist_prices

    symbols = ["AAPL"]
    _reset_watchlist_cache()

    call_count = {"n": 0}

    class _CountingTicker(_FakeTicker):
        def history(self, *a, **kw):
            call_count["n"] += 1
            return super().history(*a, **kw)

    with patch("market_data.quotes.yf.Ticker", _CountingTicker):
        result1 = fetch_watchlist_prices(symbols)
        result2 = fetch_watchlist_prices(symbols)

    assert result1 == result2
    assert call_count["n"] == 1, (
        "second call within the cache TTL must not re-invoke yfinance — "
        f"saw {call_count['n']} calls"
    )


def test_sector_performance(monkeypatch) -> None:
    """Sector grid uses one batched ``yf.download`` call for both ETFs
    (Review Finding: was one download call per ETF per period) → +10%
    first→last for each ticker, parsed out of the MultiIndex ``Close`` block.
    """
    import market_data as md

    monkeypatch.setattr("market_data.sectors._SECTOR_ETFS", {"Tech": "XLK", "Finance": "XLF"})
    _reset_sector_cache()

    idx = pd.date_range("2026-01-01", periods=10, freq="D")

    def _fake_download(tickers, **_kwargs):
        close = {t: np.linspace(100.0, 110.0, len(idx)) for t in tickers}
        df = pd.DataFrame(close, index=idx)
        df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
        return df

    with patch("market_data.sectors.yf.download", side_effect=_fake_download) as mock_dl:
        out = md.fetch_sector_performance(["1mo"])
    assert out["Tech"]["1mo"] == pytest.approx(10.0, rel=1e-9)
    assert out["Finance"]["1mo"] == pytest.approx(10.0, rel=1e-9)
    assert mock_dl.call_count == 1, "both ETFs must be fetched in a single batched download call"


def test_sector_performance_fail_silent(monkeypatch) -> None:
    """yfinance error → ``None`` for that sector's cells."""

    def _boom(*_a, **_k):
        raise RuntimeError("offline")

    import market_data as md

    monkeypatch.setattr("market_data.sectors._SECTOR_ETFS", {"Tech": "XLK", "Finance": "XLF"})
    _reset_sector_cache()
    monkeypatch.setattr(md.yf, "download", _boom)
    out = md.fetch_sector_performance(["5d"])
    assert out["Tech"]["5d"] is None
    assert out["Finance"]["5d"] is None


def test_correlation_matrix(monkeypatch) -> None:
    """Multi-ticker ``yf.download`` → square correlation matrix."""
    import market_data as md

    _reset_corr_cache()
    dates = pd.date_range("2026-01-01", periods=12, freq="D")
    pa = 100.0 + np.arange(len(dates), dtype=float) * 0.5
    pb = 200.0 + np.arange(len(dates), dtype=float) * 1.0
    cols = pd.MultiIndex.from_product(
        [["Close"], ["AAPL", "MSFT"]],
        names=["Price", "Ticker"],
    )
    df = pd.DataFrame(np.column_stack([pa, pb]), index=dates, columns=cols)

    monkeypatch.setattr(md.yf, "download", lambda *_a, **_k: df)
    payload = md.fetch_correlation_matrix(["AAPL", "MSFT"], period="3mo")
    syms = payload["symbols"]
    mat = payload["matrix"]
    assert syms == ["AAPL", "MSFT"]
    assert len(mat) == 2 and len(mat[0]) == 2
    assert mat[0][0] == pytest.approx(1.0)
    assert mat[1][1] == pytest.approx(1.0)
    assert mat[0][1] == pytest.approx(1.0, abs=1e-9)
    assert mat[1][0] == pytest.approx(1.0, abs=1e-9)


def test_correlation_matrix_multiindex(monkeypatch) -> None:
    """Full MultiIndex OHLC block still yields ``df['Close']`` width-2 frame."""
    import market_data as md

    _reset_corr_cache()
    dates = pd.date_range("2026-01-01", periods=12, freq="D")
    n = len(dates)
    close_a = 100.0 + np.linspace(0, 1, n)
    close_b = 50.0 + np.linspace(0, 2, n)
    high_a = close_a + 0.5
    tuples = [
        ("Close", "AAPL"),
        ("Close", "GOOG"),
        ("High", "AAPL"),
        ("High", "GOOG"),
    ]
    cols = pd.MultiIndex.from_tuples(tuples, names=["Price", "Ticker"])
    arr = np.column_stack([close_a, close_b, high_a, close_b + 0.5])
    df = pd.DataFrame(arr, index=dates, columns=cols)

    monkeypatch.setattr(md.yf, "download", lambda *_a, **_k: df)
    payload = md.fetch_correlation_matrix(["AAPL", "GOOG"], period="6mo")
    assert payload["symbols"] == ["AAPL", "GOOG"]
    m = payload["matrix"]
    assert len(m) == 2 and all(len(r) == 2 for r in m)
    assert m[0][0] == pytest.approx(1.0)
    assert m[1][1] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Legacy runner (for backward compat with `uv run python tests/test_terminal.py`)

_results: list[tuple[str, bool, str]] = []


def _run(name: str, fn) -> bool:
    try:
        fn()
        _results.append((name, True, ""))
        print(f"  [PASS] {name}")
        return True
    except Exception as e:
        tb = traceback.format_exc()
        _results.append((name, False, str(e)))
        print(f"  [FAIL] {name}: {e}")
        print(tb)
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("  APEX-7 Terminal / market_data Tests")
    print("=" * 60)

    tests = [
        ("test_fetch_macro", test_fetch_macro),
        ("test_fetch_watchlist_prices", test_fetch_watchlist_prices),
        ("test_fetch_news", test_fetch_news),
        ("test_run_screener", test_run_screener),
        ("test_fetch_sparkline", test_fetch_sparkline),
        ("test_fetch_comparison", test_fetch_comparison),
        ("test_cache_behavior", test_cache_behavior),
    ]

    for name, fn in tests:
        _run(name, fn)

    print()
    print("=" * 60)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"  Results: {passed}/{len(_results)} passed")
    if failed:
        print("  FAILED tests:")
        for name, ok, err in _results:
            if not ok:
                print(f"    - {name}: {err}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
