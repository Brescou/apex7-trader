"""Calendrier des résultats via yfinance — cache 5 min."""

import logging
import time
from datetime import date
from typing import Any

from market_data.caches import EARNINGS_TTL, _earnings_cache, _earnings_lock
from market_data.compat import yf
from market_data.helpers import coerce_to_date, extract_next_earnings_raw

logger = logging.getLogger("apex7.market_data")


def fetch_earnings_calendar(symbols: list[str]) -> dict[str, dict[str, Any] | None]:
    """Fetch next earnings dates for each symbol via yfinance ``Ticker.calendar``.

    Returns per symbol either ``{"earnings_date": str, "days_until": int | None}``
    or ``None`` when unavailable.

    Cached 5 minutes *per symbol* (thread-safe). Caching used to be keyed on
    the whole requested symbol set: a watchlist-wide call and a single-symbol
    ``is_earnings_week`` lookup produced different cache keys and evicted
    each other's entry every time, so the 5-minute TTL never actually held
    and every lookup hit yfinance. Per-symbol entries are shared by both.
    """
    normalized = sorted({(s or "").strip().upper() for s in symbols if (s or "").strip()})
    if not normalized:
        return {}

    now = time.time()
    result: dict[str, dict[str, Any] | None] = {}
    to_fetch: list[str] = []

    with _earnings_lock:
        cache = _earnings_cache.get("data") or {}
        for sym in normalized:
            entry = cache.get(sym)
            if entry is not None and (now - entry["ts"]) < EARNINGS_TTL:
                result[sym] = None if entry["result"] is None else dict(entry["result"])
            else:
                to_fetch.append(sym)

    if not to_fetch:
        return result

    today = date.today()
    fetched: dict[str, dict[str, Any] | None] = {}
    for usym in to_fetch:
        try:
            cal = yf.Ticker(usym).calendar
            if cal is not None and not (getattr(cal, "empty", False)):
                raw_ed = extract_next_earnings_raw(cal)
                ed = coerce_to_date(raw_ed)
                if ed is not None:
                    days_until = (ed - today).days
                    fetched[usym] = {
                        "earnings_date": str(ed),
                        "days_until": days_until,
                    }
                    continue
        except Exception:
            logger.debug("Earnings calendar failed for %s", usym)
        fetched[usym] = None

    with _earnings_lock:
        cache = _earnings_cache.get("data") or {}
        for sym, val in fetched.items():
            cache[sym] = {"result": val, "ts": time.time()}
        _earnings_cache["data"] = cache

    result.update({k: (None if v is None else dict(v)) for k, v in fetched.items()})
    return result


def is_earnings_week(symbol: str) -> bool:
    """Return True if earnings fall within the next 5 calendar days (inclusive)."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return False
    cal = fetch_earnings_calendar([sym])
    entry = cal.get(sym)
    if entry and entry.get("days_until") is not None:
        days = entry["days_until"]
        return 0 <= days <= 5
    return False
