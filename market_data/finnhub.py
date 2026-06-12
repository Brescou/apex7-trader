"""Finnhub quote fallback — used when the yfinance circuit breaker is open.

Only the ``/quote`` endpoint is used (free tier, no key required for plain
US stock/ETF tickers; ``FINNHUB_API_KEY`` lifts the rate limit from 30 to 60
req/min). Symbols with special characters (``^VIX``, ``DX-Y.NYB``) are
silently skipped — they are not available on Finnhub free tier.

Results are cached ``_FINNHUB_CACHE_SEC`` seconds per symbol. Network errors
are swallowed (debug log only) so callers never raise.
"""

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger("apex7.market_data")

_FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
_FINNHUB_CACHE_SEC = 10.0

# Per-symbol TTL cache: {symbol: {"data": dict|None, "ts": float}}
_fh_cache: dict[str, dict[str, Any]] = {}
_fh_lock = threading.Lock()


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
    url = f"{_FINNHUB_QUOTE_URL}?symbol={symbol}"
    if key:
        url += f"&token={key}"

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
