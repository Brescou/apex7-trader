"""Calendrier économique : macro statique + résultats yfinance."""

import logging
from datetime import date, datetime, timedelta
from typing import Any

from market_data.earnings import fetch_earnings_calendar

logger = logging.getLogger("apex7.market_data")

# ⚠️ UPDATE QUARTERLY — last verified: 2026-Q2
# If today > last date in list, logger.warning fires automatically
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
    if _SCHEDULED_MACRO_EVENTS:
        last_event_date = max(e["date"] for e in _SCHEDULED_MACRO_EVENTS)
        if datetime.now().strftime("%Y-%m-%d") > last_event_date:
            logger.warning(
                "_SCHEDULED_MACRO_EVENTS is stale — last event was %s. "
                "Update ``market_data/economic_calendar.py``.",
                last_event_date,
            )

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
