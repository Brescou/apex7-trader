"""
market_data.py — Standalone market data module for APEX-7 dashboard.
No imports from agent.py or agent_multi.py.
Thread-safe in-memory cache for macro (60s) and watchlist prices (10s).
"""

import threading
import time
from datetime import datetime

import yfinance as yf

from config import MACRO_SYMBOLS, MARKET_DATA_CACHE_SEC, WATCHLIST_CACHE_SEC, NEWS_MAX_ITEMS

# ─── Cache structures ────────────────────────────────────────────────────────

_macro_cache: dict = {"data": None, "ts": 0.0}
_macro_lock = threading.Lock()

_watchlist_cache: dict = {"data": None, "ts": 0.0, "key": ""}
_watchlist_lock = threading.Lock()

_sparkline_cache: dict = {}  # symbol → {"data": [...], "ts": float}
_sparkline_lock = threading.Lock()

_comparison_cache: dict = {}  # "sym1,sym2|period" → {"data": {...}, "ts": float}
_comparison_lock = threading.Lock()

_ohlcv_cache: dict = {}  # "symbol|period" → {"data": [...], "ts": float}
_ohlcv_lock = threading.Lock()

_SPARKLINE_CACHE_SEC = 300
_COMPARISON_CACHE_SEC = 300
_OHLCV_CACHE_SEC = 300


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _format_age(ts: int) -> str:
    """Format a Unix timestamp as 'Xm ago', 'Xh ago', or 'Xd ago'."""
    try:
        delta = datetime.now() - datetime.fromtimestamp(ts)
        total_seconds = int(delta.total_seconds())
        if total_seconds < 3600:
            return f"{max(1, total_seconds // 60)}m ago"
        elif total_seconds < 86400:
            return f"{total_seconds // 3600}h ago"
        else:
            return f"{total_seconds // 86400}d ago"
    except Exception:
        return "?"


_POSITIVE_WORDS = {
    "beat",
    "surge",
    "gain",
    "rise",
    "up",
    "record",
    "strong",
    "rally",
    "soar",
    "top",
}
_NEGATIVE_WORDS = {
    "miss",
    "drop",
    "fall",
    "loss",
    "down",
    "weak",
    "cut",
    "warning",
    "crash",
    "decline",
    "sell",
}


def _classify_sentiment(title: str) -> str:
    words = set(title.lower().split())
    pos = len(words & _POSITIVE_WORDS)
    neg = len(words & _NEGATIVE_WORDS)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _calc_rsi(closes: list, period: int = 14) -> float | None:
    """Wilder RSI from a list of closing prices. Returns None if insufficient data."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    # Use only the last `period` deltas
    recent = deltas[-period:]
    avg_gain = sum(d for d in recent if d > 0) / period
    avg_loss = sum(-d for d in recent if d < 0) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _format_volume(vol: float) -> str:
    if vol >= 1_000_000_000:
        return f"{vol / 1_000_000_000:.1f}B"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.1f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.1f}K"
    return str(int(vol))


# ─── Public API ──────────────────────────────────────────────────────────────


def fetch_macro() -> dict:
    """
    Fetch VIX, SPY, DXY via yfinance.
    Returns price, change_pct, direction per symbol + updated_at timestamp.
    Cached 60s. Falls back to last known value on failure.
    """
    with _macro_lock:
        now = time.time()
        if _macro_cache["data"] is not None and (now - _macro_cache["ts"]) < MARKET_DATA_CACHE_SEC:
            return _macro_cache["data"]

        result: dict = {}
        try:
            for label, ticker_sym in MACRO_SYMBOLS.items():
                hist = yf.Ticker(ticker_sym).history(period="5d", interval="1d")
                if hist.empty or len(hist) < 2:
                    result[label] = {"price": None, "change_pct": 0.0, "direction": "flat"}
                    continue
                closes = hist["Close"].tolist()
                price = round(closes[-1], 2)
                prev = closes[-2]
                change_pct = round((price - prev) / prev * 100, 2) if prev else 0.0
                if change_pct > 0.05:
                    direction = "up"
                elif change_pct < -0.05:
                    direction = "down"
                else:
                    direction = "flat"
                result[label] = {"price": price, "change_pct": change_pct, "direction": direction}

            result["updated_at"] = datetime.now().strftime("%H:%M:%S")
            _macro_cache["data"] = result
            _macro_cache["ts"] = now
        except Exception:
            # Fallback to last known data
            if _macro_cache["data"] is not None:
                return _macro_cache["data"]

        return result


def fetch_watchlist_prices(symbols: list[str]) -> dict:
    """
    Fetch live prices + indicators for a list of symbols.
    Returns price, change_pct, change_abs, volume, high_52w, low_52w, rsi_14, above_ma20.
    Cached 10s per symbol set.
    """
    cache_key = ",".join(sorted(symbols))
    with _watchlist_lock:
        now = time.time()
        if (
            _watchlist_cache["data"] is not None
            and _watchlist_cache["key"] == cache_key
            and (now - _watchlist_cache["ts"]) < WATCHLIST_CACHE_SEC
        ):
            return _watchlist_cache["data"]

        result: dict = {}
        for sym in symbols:
            try:
                hist = yf.Ticker(sym).history(period="1y", interval="1d")
                if hist.empty or len(hist) < 2:
                    result[sym] = {
                        "price": None,
                        "change_pct": 0.0,
                        "change_abs": 0.0,
                        "volume": 0,
                        "high_52w": None,
                        "low_52w": None,
                        "rsi_14": None,
                        "above_ma20": False,
                    }
                    continue
                closes = hist["Close"].tolist()
                volumes = hist["Volume"].tolist()
                price = round(closes[-1], 2)
                prev = closes[-2]
                change_abs = round(price - prev, 2)
                change_pct = round(change_abs / prev * 100, 2) if prev else 0.0
                volume = int(volumes[-1]) if volumes else 0
                high_52w = round(max(closes), 2)
                low_52w = round(min(closes), 2)
                rsi_14 = _calc_rsi(closes, 14)
                above_ma20 = (
                    price > (sum(closes[-20:]) / min(20, len(closes)))
                    if len(closes) >= 1
                    else False
                )
                result[sym] = {
                    "price": price,
                    "change_pct": change_pct,
                    "change_abs": change_abs,
                    "volume": volume,
                    "high_52w": high_52w,
                    "low_52w": low_52w,
                    "rsi_14": rsi_14 if rsi_14 is not None else 50.0,
                    "above_ma20": bool(above_ma20),
                }
            except Exception:
                result[sym] = {
                    "price": None,
                    "change_pct": 0.0,
                    "change_abs": 0.0,
                    "volume": 0,
                    "high_52w": None,
                    "low_52w": None,
                    "rsi_14": 50.0,
                    "above_ma20": False,
                }

        _watchlist_cache["data"] = result
        _watchlist_cache["key"] = cache_key
        _watchlist_cache["ts"] = now
        return result


def fetch_news(symbol: str, max_items: int = NEWS_MAX_ITEMS) -> list[dict]:
    """
    Fetch recent headlines for a symbol via yfinance Ticker.news.
    Returns title, source, age, url, sentiment.
    """
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news or []
        items = []
        for item in raw_news[:max_items]:
            # yfinance news item structure varies — handle both old and new formats
            content = item.get("content", {})
            title = item.get("title", "")
            if not title and isinstance(content, dict):
                title = content.get("title", "")
            if isinstance(content, dict):
                source = content.get("provider", {}).get(
                    "displayName", item.get("publisher", "Unknown")
                )
                url = content.get("canonicalUrl", {}).get("url", item.get("link", ""))
                pub_time = content.get("pubDate", "")
                if pub_time:
                    try:
                        dt = datetime.fromisoformat(pub_time.replace("Z", "+00:00"))
                        ts = int(dt.timestamp())
                    except Exception:
                        ts = item.get("providerPublishTime", 0)
                else:
                    ts = item.get("providerPublishTime", 0)
            else:
                source = item.get("publisher", "Unknown")
                url = item.get("link", "")
                ts = item.get("providerPublishTime", 0)

            items.append(
                {
                    "title": title,
                    "source": source,
                    "age": _format_age(ts),
                    "url": url,
                    "sentiment": _classify_sentiment(title),
                }
            )
        return items
    except Exception:
        return []


def fetch_sparkline(symbol: str) -> list[dict]:
    """
    Fetch 1-day hourly OHLC data for sparkline rendering.
    Returns: [{"time": "14:00", "price": 182.5, "open": 181.0}, ...]
    Cached 5 minutes per symbol. Returns empty list on failure.
    """
    with _sparkline_lock:
        now = time.time()
        cached = _sparkline_cache.get(symbol)
        if cached is not None and (now - cached["ts"]) < _SPARKLINE_CACHE_SEC:
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
        if cached is not None and (now - cached["ts"]) < _COMPARISON_CACHE_SEC:
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
                    {"date": d, "value": round(c / first * 100.0, 4)} for d, c in zip(dates, closes)
                ]
            _comparison_cache[cache_key] = {"data": result, "ts": now}
            return result
        except Exception:
            return {}


def fetch_ohlcv(symbol: str, period: str = "1mo") -> list[dict]:
    """
    Fetch daily OHLCV data for a symbol.
    Returns: [{"date": "2025-02-01", "open": 180.0, "high": 185.0, "low": 178.0, "close": 182.5, "volume": 45230000}, ...]
    Cached 5 minutes per (symbol, period). Returns empty list on failure, never raises.
    """
    cache_key = f"{symbol}|{period}"
    with _ohlcv_lock:
        now = time.time()
        cached = _ohlcv_cache.get(cache_key)
        if cached is not None and (now - cached["ts"]) < _OHLCV_CACHE_SEC:
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


def run_screener(symbols: list[str], filters: dict) -> list[dict]:
    """
    Filter symbols from the watchlist by the given criteria.
    Reuses fetch_watchlist_prices() — no extra network calls.
    filters keys: rsi_min, rsi_max, change_pct_min, change_pct_max, above_ma20, volume_min
    """
    prices = fetch_watchlist_prices(symbols)
    results = []
    for sym, data in prices.items():
        if data.get("price") is None:
            continue
        rsi = data.get("rsi_14", 50.0)
        if "rsi_min" in filters and rsi < filters["rsi_min"]:
            continue
        if "rsi_max" in filters and rsi > filters["rsi_max"]:
            continue
        if "change_pct_min" in filters and data["change_pct"] < filters["change_pct_min"]:
            continue
        if "change_pct_max" in filters and data["change_pct"] > filters["change_pct_max"]:
            continue
        if "above_ma20" in filters and data["above_ma20"] != filters["above_ma20"]:
            continue
        if "volume_min" in filters and data["volume"] < filters["volume_min"]:
            continue
        results.append({"symbol": sym, **data})
    return results
