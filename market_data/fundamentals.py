"""Fondamentaux par symbole (P/E, dividende, market cap…) via ``yf.Ticker.info``.

Cache mémoire 1 h par symbole — ``yf.Ticker(...).info`` est lourd et
rate-limité, à ne jamais appeler par tick. Fail-silent : renvoie le cache
stale (ou ``{}``) si yfinance échoue.
"""

import threading
import time

from market_data.caches import record_yf_failure, record_yf_success, yf_circuit_open
from market_data.compat import yf

_FUNDAMENTALS_TTL = 3600.0  # 1 hour
_fundamentals_cache: dict = {}
_fundamentals_lock = threading.Lock()

# Public key → yfinance ``.info`` key
_FIELDS = {
    "name": "shortName",
    "sector": "sector",
    "industry": "industry",
    "market_cap": "marketCap",
    "pe_ratio": "trailingPE",
    "forward_pe": "forwardPE",
    "eps": "trailingEps",
    "dividend_yield": "dividendYield",
    "beta": "beta",
    "fifty_two_week_high": "fiftyTwoWeekHigh",
    "fifty_two_week_low": "fiftyTwoWeekLow",
}


def fetch_fundamentals(symbol: str) -> dict:
    """Fundamental metrics for ``symbol`` (cached 1 h).

    Returns a dict with the :data:`_FIELDS` keys (values may be ``None`` when
    yfinance omits them). On error, serves the last cached payload if present,
    else ``{}``.
    """
    key = (symbol or "").strip().upper()
    if not key:
        return {}
    with _fundamentals_lock:
        now = time.time()
        cached = _fundamentals_cache.get(key)
        if cached is not None and (now - cached["ts"]) < _FUNDAMENTALS_TTL:
            return cached["data"]
        stale = cached["data"] if cached is not None else {}
        if yf_circuit_open():
            return stale

    # Network I/O outside the lock — yf.Ticker(...).info is a heavy call and
    # holding _fundamentals_lock across it would block every other symbol's
    # lookup (screener, chart strip) behind one global lock (Review Finding).
    result = stale
    try:
        info = yf.Ticker(key).info or {}
        record_yf_success()
        result = {pub: info.get(src) for pub, src in _FIELDS.items()}
    except Exception:
        # Bump ts along with everyone else on failure too — otherwise every
        # call while yfinance is down retries immediately instead of
        # respecting the TTL like a successful fetch would (Review Finding).
        record_yf_failure()

    with _fundamentals_lock:
        _fundamentals_cache[key] = {"data": result, "ts": time.time()}
    return result


def format_market_cap(value) -> str:
    """Human-readable market cap (e.g. ``$2.95T``, ``$48.2B``, ``$910M``)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if v <= 0:
        return "—"
    for unit, scale in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= scale:
            return f"${v / scale:.2f}{unit}"
    return f"${v:.0f}"
