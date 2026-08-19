"""Finnhub quote + company-news fallback.

``/quote`` is used when the yfinance circuit breaker is open. ``/company-news``
backs ``fetch_news`` when yfinance returns nothing. Both need ``FINNHUB_API_KEY``
in ``.env`` — unauthenticated calls 401. Symbols with special characters
(``^VIX``, ``DX-Y.NYB``) are skipped (not on the free tier).

Results are cached ``_FINNHUB_CACHE_SEC`` seconds per symbol. Network errors
are swallowed (debug log only) so callers never raise; a missing API key is
logged once at WARNING level so it doesn't disappear into debug noise.
"""

import logging
import threading
import time
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger("apex7.market_data")

_FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
_FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"
_FINNHUB_CACHE_SEC = 10.0
_FINNHUB_NEWS_CACHE_SEC = 120.0

# Per-symbol TTL cache: {symbol: {"data": dict|None, "ts": float}}
_fh_cache: dict[str, dict[str, Any]] = {}
_fh_lock = threading.Lock()
_fh_news_cache: dict[str, dict[str, Any]] = {}
_fh_news_lock = threading.Lock()

# Warn about a missing key once per process, not once per failed quote —
# this fallback is only exercised while yfinance is already down, so a
# per-call warning would flood the logs exactly when they matter most.
_missing_key_warned = False


def _api_key() -> str:
    import config

    return (getattr(config, "FINNHUB_API_KEY", "") or "").strip()


def _is_plain_ticker(sym: str) -> bool:
    """Return True for plain US stock/ETF tickers (letters only, 1–5 chars).

    Rejects ``^VIX``, ``DX-Y.NYB``, empty strings, etc. — Finnhub free tier
    does not support index symbols.
    """
    return bool(sym) and sym.isalpha() and sym.isupper() and 1 <= len(sym) <= 5


def fetch_finnhub_quote(symbol: str) -> dict[str, Any] | None:
    """Fetch a single quote from Finnhub ``/quote``.

    Returns a dict with ``price``, ``change_abs``, ``change_pct``, ``high``,
    ``low``, ``prev_close`` — or ``None`` on failure / unsupported symbol.
    Cached ``_FINNHUB_CACHE_SEC`` seconds.

    Args:
        symbol: Plain ticker (e.g. ``"AAPL"``, ``"SPY"``). Symbols with
            special characters are rejected immediately (returns ``None``).
    """
    if not _is_plain_ticker(symbol):
        return None

    now = time.time()
    with _fh_lock:
        cached = _fh_cache.get(symbol)
        if cached is not None and (now - cached["ts"]) < _FINNHUB_CACHE_SEC:
            return cached["data"]

    key = _api_key()
    if not key:
        global _missing_key_warned
        if not _missing_key_warned:
            _missing_key_warned = True
            logger.warning(
                "FINNHUB_API_KEY not set — Finnhub /quote rejects unauthenticated "
                "requests, so the yfinance-outage fallback will not work until it "
                "is configured (this warning fires once per process)."
            )
        with _fh_lock:
            _fh_cache[symbol] = {"data": None, "ts": time.time()}
        return None

    url = f"{_FINNHUB_QUOTE_URL}?symbol={symbol}&token={key}"

    result: dict[str, Any] | None = None
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
        price = data.get("c")
        if price:
            result = {
                "price": round(float(price), 2),
                "change_abs": round(float(data.get("d") or 0.0), 2),
                "change_pct": round(float(data.get("dp") or 0.0), 2),
                "high": round(float(data.get("h") or price), 2),
                "low": round(float(data.get("l") or price), 2),
                "prev_close": round(float(data.get("pc") or price), 2),
            }
    except Exception:
        logger.debug("Finnhub quote failed for %s", symbol)

    with _fh_lock:
        _fh_cache[symbol] = {"data": result, "ts": time.time()}
    return result


def fetch_finnhub_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch quotes for multiple symbols; only resolved ones appear in the result."""
    out: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        q = fetch_finnhub_quote(sym)
        if q is not None:
            out[sym] = q
    return out


def fetch_finnhub_news(symbol: str, max_items: int | None = None) -> list[dict[str, Any]]:
    """Fetch company headlines from Finnhub ``/company-news``.

    Returns the same shape as ``market_data.news.fetch_news``:
    ``title``, ``source``, ``age``, ``url``, ``sentiment``. Empty list on
    missing key, unsupported symbol, or network error.

    The full 14-day window is fetched once and cached per symbol; ``max_items``
    only slices that list.
    """
    from config import NEWS_MAX_ITEMS, NEWS_MAX_TOTAL

    cap = NEWS_MAX_ITEMS if max_items is None else max(0, min(int(max_items), NEWS_MAX_TOTAL))
    return _finnhub_news_pool(symbol)[:cap]


def _finnhub_news_pool(symbol: str) -> list[dict[str, Any]]:
    if not _is_plain_ticker(symbol):
        return []

    now = time.time()
    with _fh_news_lock:
        cached = _fh_news_cache.get(symbol)
        if cached is not None and (now - cached["ts"]) < _FINNHUB_NEWS_CACHE_SEC:
            return cached["data"]

    from config import NEWS_MAX_TOTAL

    key = _api_key()
    items: list[dict[str, Any]] = []
    if key:
        to_d = date.today()
        from_d = to_d - timedelta(days=14)
        url = (
            f"{_FINNHUB_NEWS_URL}?symbol={symbol}"
            f"&from={from_d.isoformat()}&to={to_d.isoformat()}&token={key}"
        )
        try:
            from market_data.helpers import classify_sentiment, format_age

            with httpx.Client(timeout=8.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                raw = resp.json()
            if isinstance(raw, list):
                for row in raw:
                    if len(items) >= NEWS_MAX_TOTAL:
                        break
                    title = (row.get("headline") or "").strip()
                    if not title:
                        continue
                    ts = int(row.get("datetime") or 0)
                    items.append(
                        {
                            "title": title,
                            "source": row.get("source") or "Finnhub",
                            "age": format_age(ts),
                            "url": row.get("url") or "",
                            "sentiment": classify_sentiment(title),
                            "_ts": ts,
                        }
                    )
        except Exception:
            logger.debug("Finnhub news failed for %s", symbol)

    with _fh_news_lock:
        _fh_news_cache[symbol] = {"data": items, "ts": time.time()}
    return items
