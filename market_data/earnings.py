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

    Cached 5 minutes per distinct normalized symbol set (thread-safe), to avoid
    hammering yfinance on every terminal tick.
    """
    cache_key = ",".join(sorted({(s or "").strip().upper() for s in symbols if (s or "").strip()}))
    if not cache_key:
        return {}

    with _earnings_lock:
        now = time.time()
        cached = _earnings_cache.get("data")
        if (
            cached is not None
            and _earnings_cache.get("key") == cache_key
            and (now - float(_earnings_cache.get("ts") or 0)) < EARNINGS_TTL
        ):
            return {k: None if v is None else dict(v) for k, v in cached.items()}

    result: dict[str, dict[str, Any] | None] = {}
    today = date.today()
    for sym in symbols:
        raw = (sym or "").strip()
        if not raw:
            continue
        usym = raw.upper()
        try:
            cal = yf.Ticker(usym).calendar
            if cal is not None and not (getattr(cal, "empty", False)):
                raw_ed = extract_next_earnings_raw(cal)
                ed = coerce_to_date(raw_ed)
                if ed is not None:
                    days_until = (ed - today).days
                    result[usym] = {
                        "earnings_date": str(ed),
                        "days_until": days_until,
                    }
                    continue
        except Exception:
            logger.debug("Earnings calendar failed for %s", usym)
        result[usym] = None

    with _earnings_lock:
        _earnings_cache["data"] = result
        _earnings_cache["key"] = cache_key
        _earnings_cache["ts"] = time.time()
    return {k: None if v is None else dict(v) for k, v in result.items()}


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
