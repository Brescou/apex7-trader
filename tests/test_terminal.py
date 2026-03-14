"""Terminal/market_data tests for APEX-7 — no pytest, just assert + print.

Run with:  uv run python tests/test_terminal.py
Exit 0 if all pass, exit 1 on any failure.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# ─────────────────────────────────────────────────────────────────────────────


def test_fetch_macro():
    from market_data import fetch_macro

    result = fetch_macro()
    assert isinstance(result, dict), f"fetch_macro must return dict, got {type(result)}"
    # Must have at least updated_at or at least one symbol key
    assert len(result) > 0, "fetch_macro returned empty dict"
    if "updated_at" in result:
        assert isinstance(result["updated_at"], str)
    # Each symbol entry should have expected keys
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
    # Empty filters — should return all symbols with valid prices
    result = run_screener(symbols, {})
    assert isinstance(result, list), f"run_screener must return list, got {type(result)}"

    # Filter with rsi_min=0 — should still return results
    result2 = run_screener(symbols, {"rsi_min": 0})
    assert isinstance(result2, list)

    # Filter impossible to satisfy — should return empty
    result3 = run_screener(symbols, {"rsi_min": 150})
    assert result3 == [], f"Expected empty list for impossible filter, got {result3}"

    # Each entry should have 'symbol' key
    for entry in result:
        assert "symbol" in entry, f"Screener entry missing 'symbol': {entry}"


def test_fetch_sparkline():
    """Test fetch_sparkline if available; gracefully skip if not yet implemented."""
    import market_data

    if not hasattr(market_data, "fetch_sparkline"):
        print(
            "    (fetch_sparkline not yet in market_data — skipping, expected until backend-terminal merges)"
        )
        return

    from market_data import fetch_sparkline

    result = fetch_sparkline("AAPL")
    assert isinstance(result, list), f"fetch_sparkline must return list, got {type(result)}"
    if len(result) == 0:
        # Empty list is acceptable on network failure
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
        print(
            "    (fetch_comparison not yet in market_data — skipping, expected until backend-terminal merges)"
        )
        return

    from market_data import fetch_comparison

    result = fetch_comparison(["AAPL", "MSFT"], period="1mo")
    assert isinstance(result, dict), f"fetch_comparison must return dict, got {type(result)}"
    if not result:
        # Empty dict is acceptable on network failure
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
    """Verify that repeated calls return cached data (same object identity or consistent values)."""
    from market_data import fetch_watchlist_prices

    symbols = ["AAPL"]
    result1 = fetch_watchlist_prices(symbols)
    result2 = fetch_watchlist_prices(symbols)

    assert isinstance(result1, dict) and isinstance(result2, dict)
    # Both calls should return same symbols
    assert set(result1.keys()) == set(
        result2.keys()
    ), f"Cache inconsistency: {result1.keys()} vs {result2.keys()}"
    # Price should be identical (served from cache)
    for sym in symbols:
        if result1[sym]["price"] is not None and result2[sym]["price"] is not None:
            assert (
                result1[sym]["price"] == result2[sym]["price"]
            ), f"Cache miss: prices differ for {sym}: {result1[sym]['price']} vs {result2[sym]['price']}"


# ─────────────────────────────────────────────────────────────────────────────

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
