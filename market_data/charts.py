"""Sparklines, comparaison multi-symboles, OHLCV quotidien."""

import time

from market_data.caches import (
    COMPARISON_CACHE_SEC,
    OHLCV_CACHE_SEC,
    SPARKLINE_CACHE_SEC,
    _comparison_cache,
    _comparison_lock,
    _ohlcv_cache,
    _ohlcv_lock,
    _sparkline_cache,
    _sparkline_lock,
)
from market_data.compat import yf


def fetch_sparkline(symbol: str) -> list[dict]:
    """
    Fetch 1-day hourly OHLC data for sparkline rendering.
    Returns: [{"time": "14:00", "price": 182.5, "open": 181.0}, ...]
    Cached 5 minutes per symbol. Returns empty list on failure.
    """
    with _sparkline_lock:
        now = time.time()
        cached = _sparkline_cache.get(symbol)
        if cached is not None and (now - cached["ts"]) < SPARKLINE_CACHE_SEC:
            return cached["data"]

        try:
            hist = yf.Ticker(symbol).history(period="1d", interval="1h")
            if hist.empty:
                return []
            result = []
            for ts_idx, row in hist.iterrows():
                result.append(
                    {
                        "time": ts_idx.strftime("%H:%M"),
                        "price": round(float(row["Close"]), 2),
                        "open": round(float(row["Open"]), 2),
                    }
                )
            _sparkline_cache[symbol] = {"data": result, "ts": now}
            return result
        except Exception:
            return []


def fetch_comparison(symbols: list[str], period: str = "1mo") -> dict:
    """
    Fetch daily closes for multiple symbols and normalize each series to 100.0 at first point.
    Returns: {"AAPL": [{"date": "2025-02-01", "value": 100.0}, ...], "MSFT": [...]}
    Cached 5 minutes per (sorted symbols, period). Returns empty dict on failure.
    """
    cache_key = ",".join(sorted(symbols)) + "|" + period
    with _comparison_lock:
        now = time.time()
        cached = _comparison_cache.get(cache_key)
        if cached is not None and (now - cached["ts"]) < COMPARISON_CACHE_SEC:
            return cached["data"]

        try:
            result: dict = {}
            for sym in symbols:
                hist = yf.Ticker(sym).history(period=period, interval="1d")
                if hist.empty:
                    continue
                closes = hist["Close"].tolist()
                dates = hist.index.strftime("%Y-%m-%d").tolist()
                first = closes[0]
                if first == 0:
                    continue
                result[sym] = [
                    {"date": d_str, "value": round(c / first * 100.0, 4)}
                    for d_str, c in zip(dates, closes)
                ]
            _comparison_cache[cache_key] = {"data": result, "ts": now}
            return result
        except Exception:
            return {}


def fetch_ohlcv(symbol: str, period: str = "1mo") -> list[dict]:
    """
    Fetch daily OHLCV data for a symbol.
    Returns: [{"date": "...", "open": ..., "high": ..., "low": ..., "close": ...}, ...]
    Cached 5 minutes per (symbol, period). Returns empty list on failure, never raises.
    """
    cache_key = f"{symbol}|{period}"
    with _ohlcv_lock:
        now = time.time()
        cached = _ohlcv_cache.get(cache_key)
        if cached is not None and (now - cached["ts"]) < OHLCV_CACHE_SEC:
            return cached["data"]
        try:
            hist = yf.Ticker(symbol).history(period=period, interval="1d")
            if hist.empty:
                return []
            result = []
            for ts_idx, row in hist.iterrows():
                result.append(
                    {
                        "date": ts_idx.strftime("%Y-%m-%d"),
                        "open": round(float(row["Open"]), 4),
                        "high": round(float(row["High"]), 4),
                        "low": round(float(row["Low"]), 4),
                        "close": round(float(row["Close"]), 4),
                        "volume": int(row["Volume"]),
                    }
                )
            _ohlcv_cache[cache_key] = {"data": result, "ts": now}
            return result
        except Exception:
            return []
