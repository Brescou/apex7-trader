"""Finnhub quote fallback — used when the yfinance circuit breaker is open.

Only the ``/quote`` endpoint is used. Despite older Finnhub free-tier docs,
``/quote`` now rejects requests with no ``token`` param (401 "API key is
invalid") for every symbol — set ``FINNHUB_API_KEY`` in ``.env`` or this
fallback is a permanent no-op. Symbols with special characters (``^VIX``,
``DX-Y.NYB``) are silently skipped — they are not available on Finnhub
free tier regardless of key.

Results are cached ``_FINNHUB_CACHE_SEC`` seconds per symbol. Network errors
are swallowed (debug log only) so callers never raise; a missing API key is
logged once at WARNING level so it doesn't disappear into debug noise.
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
