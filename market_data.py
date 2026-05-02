"""
market_data.py — Standalone market data module for APEX-7 dashboard.
No imports from agent.py or agent_multi.py.
Thread-safe in-memory cache for macro (60s) and watchlist prices (10s).
"""

import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from config import MACRO_SYMBOLS, MARKET_DATA_CACHE_SEC, WATCHLIST_CACHE_SEC, NEWS_MAX_ITEMS
from core.indicators import rsi

logger = logging.getLogger("apex7.market_data")

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
_SECTOR_CACHE_SEC = 300

_sector_perf_cache: dict[str, Any] = {"data": None, "ts": 0.0, "key": ""}
_sector_perf_lock = threading.Lock()

_corr_matrix_cache: dict[str, Any] = {"data": None, "ts": 0.0, "key": ""}
_corr_matrix_lock = threading.Lock()
_CORR_MATRIX_CACHE_SEC = 300

# SPDR sector ETFs → human labels (11 sectors, Finviz-style rotation grid).
_SECTOR_ETFS: dict[str, str] = {
    "Tech": "XLK",
    "Finance": "XLF",
    "Energy": "XLE",
    "Health": "XLV",
    "Consumer": "XLY",
    "Industrial": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Comm": "XLC",
    "Staples": "XLP",
}


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


def _calc_rsi(prices: list[float], period: int = 14) -> float:
    return rsi(prices, period)


def _format_volume(vol: float) -> str:
    if vol >= 1_000_000_000:
        return f"{vol / 1_000_000_000:.1f}B"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.1f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.1f}K"
    return str(int(vol))


def _extract_next_earnings_raw(calendar: Any) -> Any:
    """Pull the next earnings date field from yfinance ``calendar`` (dict or DataFrame)."""
    if calendar is None:
        return None
    if isinstance(calendar, dict):
        ed = calendar.get("Earnings Date")
        if ed is None:
            return None
        if isinstance(ed, (list, tuple)):
            return ed[0] if len(ed) > 0 else None
        return ed
    try:
        cal_df = calendar
        if getattr(cal_df, "empty", True):
            return None
        return cal_df.iloc[0, 0]
    except Exception:
        return None


def _coerce_to_date(value: Any) -> date | None:
    """Normalize yfinance / pandas date-like values to ``datetime.date``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        try:
            return value.date()
        except Exception:
            return None
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().date()
        except Exception:
            return None
    return None


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


def fetch_earnings_calendar(symbols: list[str]) -> dict[str, dict[str, Any] | None]:
    """Fetch next earnings dates for each symbol via yfinance ``Ticker.calendar``.

    Returns per symbol either ``{"earnings_date": str, "days_until": int | None}``
    or ``None`` when unavailable.
    """
    result: dict[str, dict[str, Any] | None] = {}
    today = date.today()
    for sym in symbols:
        try:
            cal = yf.Ticker(sym).calendar
            if cal is not None and not (getattr(cal, "empty", False)):
                raw = _extract_next_earnings_raw(cal)
                ed = _coerce_to_date(raw)
                if ed is not None:
                    days_until = (ed - today).days
                    result[sym] = {
                        "earnings_date": str(ed),
                        "days_until": days_until,
                    }
                    continue
        except Exception:
            logger.debug("Earnings calendar failed for %s", sym)
        result[sym] = None
    return result


def is_earnings_week(symbol: str) -> bool:
    """Return True if earnings fall within the next 5 calendar days (inclusive)."""
    cal = fetch_earnings_calendar([symbol])
    entry = cal.get(symbol)
    if entry and entry.get("days_until") is not None:
        days = entry["days_until"]
        return 0 <= days <= 5
    return False


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


def _sector_pct_change_from_download(etf: str, period: str) -> float | None:
    """Return percent change first→last close for one ETF/period; ``None`` on failure."""
    try:
        df = yf.download(
            etf,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        if df is None or len(df) < 2:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        closes = df["Close"].dropna()
        if len(closes) < 2:
            return None
        first = float(closes.iloc[0])
        last = float(closes.iloc[-1])
        if first == 0:
            return None
        pct = (last - first) / first * 100.0
        return round(float(pct), 2)
    except Exception:
        logger.debug("sector performance failed for %s %s", etf, period, exc_info=False)
        return None


def fetch_sector_performance(
    periods: list[str] | None = None,
) -> dict[str, dict[str, float | None]]:
    """Fetch performance of each sector ETF over several yfinance periods.

    Cached 5 minutes per distinct ``periods`` list (same pattern as OHLCV/sparkline).

    Args:
        periods: yfinance ``period`` args, e.g. ``[\"1d\", \"5d\", \"1mo\"]`` for
            1 day, ~1 week, 1 month.

    Returns:
        ``{ sector_name: { period: pct_change or None } }`` aligned with
        ``_SECTOR_ETFS`` insertion order.
    """
    if periods is None:
        periods = ["1d", "5d", "1mo"]
    cache_key = "|".join(periods)
    with _sector_perf_lock:
        now = time.time()
        cached = _sector_perf_cache.get("data")
        if (
            cached is not None
            and _sector_perf_cache.get("key") == cache_key
            and (now - float(_sector_perf_cache.get("ts") or 0)) < _SECTOR_CACHE_SEC
        ):
            return {k: dict(v) for k, v in cached.items()}

    result: dict[str, dict[str, float | None]] = {}
    for name, etf in _SECTOR_ETFS.items():
        result[name] = {}
        for period in periods:
            result[name][period] = _sector_pct_change_from_download(etf, period)

    with _sector_perf_lock:
        _sector_perf_cache["data"] = result
        _sector_perf_cache["key"] = cache_key
        _sector_perf_cache["ts"] = time.time()
    return {k: dict(v) for k, v in result.items()}


def fetch_correlation_matrix(symbols: list[str], period: str = "3mo") -> dict[str, Any]:
    """Daily return correlation matrix between tickers (Pearson on ``pct_change()``).

    Up to 10 symbols; order preserved in ``symbols`` where data exists. Cached 5 minutes
    per (sorted symbols set, period).

    Returns:
        ``{"symbols": [...], "matrix": [[float, ...], ...]}`` — empty ``matrix`` on failure.
    """
    syms = [str(s).strip().upper() for s in symbols if s and str(s).strip()][:10]
    if not syms:
        return {"symbols": [], "matrix": []}
    if len(syms) == 1:
        return {"symbols": syms, "matrix": [[1.0]]}

    cache_key = f"{period}|" + ",".join(sorted(syms))
    with _corr_matrix_lock:
        now = time.time()
        cached = _corr_matrix_cache.get("data")
        if (
            cached is not None
            and _corr_matrix_cache.get("key") == cache_key
            and (now - float(_corr_matrix_cache.get("ts") or 0)) < _CORR_MATRIX_CACHE_SEC
        ):
            c = cached
            return {"symbols": list(c["symbols"]), "matrix": [list(r) for r in c["matrix"]]}

    try:
        df = yf.download(
            syms,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        if df is None or df.empty or len(df) < 5:
            out = {"symbols": syms, "matrix": []}
            with _corr_matrix_lock:
                _corr_matrix_cache["data"] = out
                _corr_matrix_cache["key"] = cache_key
                _corr_matrix_cache["ts"] = time.time()
            return {"symbols": list(out["symbols"]), "matrix": [list(r) for r in out["matrix"]]}

        if isinstance(df.columns, pd.MultiIndex) and "Close" in df.columns.get_level_values(0):
            closes = df["Close"].copy()
        else:
            out = {"symbols": syms, "matrix": []}
            with _corr_matrix_lock:
                _corr_matrix_cache["data"] = out
                _corr_matrix_cache["key"] = cache_key
                _corr_matrix_cache["ts"] = time.time()
            return {"symbols": list(out["symbols"]), "matrix": [list(r) for r in out["matrix"]]}

        present = [s for s in syms if s in closes.columns]
        if len(present) < 2:
            out = {"symbols": syms, "matrix": []}
            with _corr_matrix_lock:
                _corr_matrix_cache["data"] = out
                _corr_matrix_cache["key"] = cache_key
                _corr_matrix_cache["ts"] = time.time()
            return {"symbols": list(out["symbols"]), "matrix": [list(r) for r in out["matrix"]]}

        sub = closes[present]
        returns = sub.pct_change().dropna()
        if len(returns) < 5:
            out = {"symbols": present, "matrix": []}
            with _corr_matrix_lock:
                _corr_matrix_cache["data"] = out
                _corr_matrix_cache["key"] = cache_key
                _corr_matrix_cache["ts"] = time.time()
            return {"symbols": list(out["symbols"]), "matrix": [list(r) for r in out["matrix"]]}

        corr = returns.corr()
        order = [s for s in syms if s in corr.columns]
        subm = corr.loc[order, order]
        mat = [
            [round(float(x), 4) if pd.notna(x) else 0.0 for x in row]
            for row in subm.values.tolist()
        ]
        out = {"symbols": order, "matrix": mat}
    except Exception:
        logger.debug("Correlation matrix failed", exc_info=False)
        out = {"symbols": syms, "matrix": []}

    with _corr_matrix_lock:
        _corr_matrix_cache["data"] = out
        _corr_matrix_cache["key"] = cache_key
        _corr_matrix_cache["ts"] = time.time()
    return {"symbols": list(out["symbols"]), "matrix": [list(r) for r in out["matrix"]]}


# Scheduled macro prints (FOMC / CPI / NFP). Refresh quarterly from Fed & BLS calendars.
_SCHEDULED_MACRO_EVENTS: list[dict[str, str]] = [
    {"date": "2026-01-09", "event": "NFP", "importance": "high"},
    {"date": "2026-01-14", "event": "CPI", "importance": "high"},
    {"date": "2026-01-28", "event": "FOMC", "importance": "high"},
    {"date": "2026-02-06", "event": "NFP", "importance": "high"},
    {"date": "2026-02-11", "event": "CPI", "importance": "high"},
    {"date": "2026-03-06", "event": "NFP", "importance": "high"},
    {"date": "2026-03-11", "event": "CPI", "importance": "high"},
    {"date": "2026-03-18", "event": "FOMC", "importance": "high"},
    {"date": "2026-04-03", "event": "NFP", "importance": "high"},
    {"date": "2026-04-14", "event": "CPI", "importance": "high"},
    {"date": "2026-05-08", "event": "NFP", "importance": "high"},
    {"date": "2026-05-13", "event": "CPI", "importance": "high"},
    {"date": "2026-05-07", "event": "FOMC", "importance": "high"},
    {"date": "2026-06-05", "event": "NFP", "importance": "high"},
    {"date": "2026-06-10", "event": "CPI", "importance": "high"},
    {"date": "2026-06-17", "event": "FOMC", "importance": "high"},
    {"date": "2026-07-03", "event": "NFP", "importance": "high"},
    {"date": "2026-07-14", "event": "CPI", "importance": "high"},
    {"date": "2026-07-29", "event": "FOMC", "importance": "high"},
    {"date": "2026-08-07", "event": "NFP", "importance": "high"},
    {"date": "2026-08-12", "event": "CPI", "importance": "high"},
    {"date": "2026-09-04", "event": "NFP", "importance": "high"},
    {"date": "2026-09-10", "event": "CPI", "importance": "high"},
    {"date": "2026-09-16", "event": "FOMC", "importance": "high"},
    {"date": "2026-10-02", "event": "NFP", "importance": "high"},
    {"date": "2026-10-14", "event": "CPI", "importance": "high"},
    {"date": "2026-11-06", "event": "NFP", "importance": "high"},
    {"date": "2026-11-12", "event": "CPI", "importance": "high"},
    {"date": "2026-11-04", "event": "FOMC", "importance": "high"},
    {"date": "2026-12-04", "event": "NFP", "importance": "high"},
    {"date": "2026-12-10", "event": "CPI", "importance": "high"},
    {"date": "2026-12-16", "event": "FOMC", "importance": "high"},
]


def build_economic_calendar_rows(
    symbols: list[str],
    *,
    horizon_days: int = 120,
) -> list[dict[str, Any]]:
    """Merge yfinance earnings for ``symbols`` with the static macro schedule.

    Returns rows sorted by event date, each with ``kind`` (``earnings`` or
    ``macro``), ``event_date`` (``datetime.date``), ``days_until``, and
    metadata for UI (``symbol``, ``event``, ``importance``).

    Args:
        symbols: Watchlist tickers for ``fetch_earnings_calendar``.
        horizon_days: Only include events from today through this many days.
    """
    today = date.today()
    rows: list[dict[str, Any]] = []
    end_offset = timedelta(days=horizon_days)

    for item in _SCHEDULED_MACRO_EVENTS:
        evd = date.fromisoformat(item["date"])
        if evd < today or evd > today + end_offset:
            continue
        rows.append(
            {
                "kind": "macro",
                "event_date": evd,
                "days_until": (evd - today).days,
                "event": item["event"],
                "importance": item.get("importance", "high"),
                "symbol": None,
            }
        )

    try:
        earn = fetch_earnings_calendar(list(symbols))
    except Exception:
        logger.debug("build_economic_calendar_rows: earnings fetch failed", exc_info=False)
        earn = {}

    for sym, entry in earn.items():
        if not entry:
            continue
        raw = entry.get("earnings_date")
        if not raw:
            continue
        try:
            evd = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        du = entry.get("days_until")
        if du is None:
            du = (evd - today).days
        if du < 0 or evd > today + end_offset:
            continue
        rows.append(
            {
                "kind": "earnings",
                "event_date": evd,
                "days_until": du,
                "event": "EARNINGS",
                "importance": "medium",
                "symbol": sym,
            }
        )

    rows.sort(key=lambda r: (r["event_date"], r["kind"], r.get("symbol") or ""))
    return rows


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
