"""Terminal/market_data tests for APEX-7.

Run with:  uv run pytest tests/test_terminal.py -v
Legacy:    uv run python tests/test_terminal.py
"""

import os
import sys
import traceback
from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────


def _dash_collect_text(node) -> list[str]:
    """Flatten Dash ``html`` component tree into text fragments."""
    if node is None:
        return []
    if isinstance(node, str):
        return [node]
    if isinstance(node, (list, tuple)):
        out: list[str] = []
        for ch in node:
            out.extend(_dash_collect_text(ch))
        return out
    children = getattr(node, "children", None)
    if children is None:
        return []
    if isinstance(children, (list, tuple)):
        out: list[str] = []
        for ch in children:
            out.extend(_dash_collect_text(ch))
        return out
    return _dash_collect_text(children)


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


# ─────────────────────────────────────────────────────────────────────────────


def test_fetch_macro():
    from market_data import fetch_macro

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


def test_fetch_watchlist_prices():
    from market_data import fetch_watchlist_prices

    symbols = ["AAPL", "MSFT"]
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


def test_fetch_news():
    from market_data import fetch_news

    result = fetch_news("AAPL")
    assert isinstance(result, list), f"fetch_news must return list, got {type(result)}"
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


def test_run_screener():
    from market_data import run_screener

    symbols = ["AAPL", "MSFT", "GOOGL"]
    result = run_screener(symbols, {})
    assert isinstance(result, list), f"run_screener must return list, got {type(result)}"

    result2 = run_screener(symbols, {"rsi_min": 0})
    assert isinstance(result2, list)

    result3 = run_screener(symbols, {"rsi_min": 150})
    assert result3 == [], f"Expected empty list for impossible filter, got {result3}"

    for entry in result:
        assert "symbol" in entry, f"Screener entry missing 'symbol': {entry}"


def test_fetch_sparkline():
    """Test fetch_sparkline if available; gracefully skip if not yet implemented."""
    import market_data

    if not hasattr(market_data, "fetch_sparkline"):
        import pytest

        pytest.skip("fetch_sparkline not yet in market_data")

    from market_data import fetch_sparkline

    result = fetch_sparkline("AAPL")
    assert isinstance(result, list), f"fetch_sparkline must return list, got {type(result)}"
    if len(result) == 0:
        return
    first = result[0]
    assert "time" in first, f"Sparkline entry missing 'time': {first}"
    assert "price" in first, f"Sparkline entry missing 'price': {first}"
    assert "open" in first, f"Sparkline entry missing 'open': {first}"
    assert isinstance(first["price"], (int, float)), f"price must be numeric: {first['price']}"


def test_fetch_comparison():
    """Test fetch_comparison if available; gracefully skip if not yet implemented."""
    import market_data

    if not hasattr(market_data, "fetch_comparison"):
        import pytest

        pytest.skip("fetch_comparison not yet in market_data")

    from market_data import fetch_comparison

    result = fetch_comparison(["AAPL", "MSFT"], period="1mo")
    assert isinstance(result, dict), f"fetch_comparison must return dict, got {type(result)}"
    if not result:
        return
    for sym in ["AAPL", "MSFT"]:
        assert sym in result, f"Missing symbol {sym} in comparison result"
        series = result[sym]
        assert isinstance(series, list), f"Series for {sym} must be list"
        if len(series) > 0:
            first = series[0]
            assert "date" in first, f"Comparison entry missing 'date': {first}"
            assert "value" in first, f"Comparison entry missing 'value': {first}"
            assert (
                first["value"] == 100.0
            ), f"First value must be normalized to 100.0, got {first['value']}"


def test_cache_behavior():
    """Verify that repeated calls return cached data."""
    from market_data import fetch_watchlist_prices

    symbols = ["AAPL"]
    result1 = fetch_watchlist_prices(symbols)
    result2 = fetch_watchlist_prices(symbols)

    assert isinstance(result1, dict) and isinstance(result2, dict)
    assert set(result1.keys()) == set(
        result2.keys()
    ), f"Cache inconsistency: {result1.keys()} vs {result2.keys()}"
    for sym in symbols:
        if result1[sym]["price"] is not None and result2[sym]["price"] is not None:
            assert (
                result1[sym]["price"] == result2[sym]["price"]
            ), f"Cache miss: prices differ for {sym}: {result1[sym]['price']} vs {result2[sym]['price']}"


def test_sector_performance(monkeypatch) -> None:
    """Sector grid uses ``yf.download`` closes; two ETFs → +10% first→last."""
    import market_data as md

    monkeypatch.setattr("market_data.sectors._SECTOR_ETFS", {"Tech": "XLK", "Finance": "XLF"})
    _reset_sector_cache()

    idx = pd.date_range("2026-01-01", periods=10, freq="D")

    def _fake_download(_ticker, **_kwargs):
        close = np.linspace(100.0, 110.0, len(idx))
        return pd.DataFrame({"Close": close}, index=idx)

    monkeypatch.setattr(md.yf, "download", _fake_download)
    out = md.fetch_sector_performance(["1mo"])
    assert out["Tech"]["1mo"] == pytest.approx(10.0, rel=1e-9)
    assert out["Finance"]["1mo"] == pytest.approx(10.0, rel=1e-9)


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


def test_fear_greed_in_macro() -> None:
    """Macro bar callback surfaces CNN Fear & Greed score when mocked."""
    import dashboard.callbacks.terminal as term

    macro_stub = {
        "updated_at": "",
        "VIX": {"price": 18.0, "change_pct": 1.0, "direction": "up"},
        "SPY": {"price": 500.0, "change_pct": 0.5, "direction": "up"},
        "DXY": {"price": 104.0, "change_pct": -0.1, "direction": "down"},
    }
    fed_stub = {"value": 4.5, "date": "2026-01-01"}

    with patch.object(term, "fetch_fear_greed", return_value={"score": 72, "label": "Greed"}):
        with patch.object(term, "fetch_fred_latest", return_value=fed_stub):
            with patch.object(term, "fetch_macro", return_value=macro_stub):
                with patch.object(term, "fetch_sparkline", return_value=[]):
                    children = term._update_macro_bar(0)
    flat = " ".join(_dash_collect_text(children))
    assert "F&G: 72" in flat
    assert "Greed" in flat


def test_earnings_calendar_in_terminal() -> None:
    """Economic calendar callback shows mocked earnings line from watchlist."""
    import dashboard.callbacks.terminal as term

    row = {
        "kind": "earnings",
        "event_date": date(2030, 6, 10),
        "days_until": 3,
        "event": "EARNINGS",
        "symbol": "NVDA",
    }

    with patch.object(term, "build_economic_calendar_rows", return_value=[row]):
        out = term._update_economic_calendar(0, ["NVDA", "AAPL"])
    text = " ".join(_dash_collect_text(out))
    assert "NVDA" in text
    assert "earnings" in text.lower()


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
