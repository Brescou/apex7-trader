"""Calendrier économique : macro statique + résultats yfinance."""

import logging
from datetime import date, datetime, timedelta
from typing import Any

from market_data.earnings import fetch_earnings_calendar

logger = logging.getLogger("apex7.market_data")

# FRED release ids that map cleanly to our macro events. FOMC is NOT a FRED
# release (no scheduled-data feed), so it stays sourced from the static list.
_FRED_RELEASE_IDS: dict[int, str] = {
    10: "CPI",  # Consumer Price Index
    50: "NFP",  # Employment Situation (non-farm payrolls)
}

# ⚠️ FALLBACK schedule — used when FRED is unavailable (offline / rate-limited)
# and as the source of truth for FOMC dates (not a FRED release).
# UPDATE QUARTERLY — last verified: 2026-Q2. If today > last date, a
# logger.warning fires automatically.
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


def _fred_macro_events(horizon_days: int) -> list[dict[str, str]]:
    """CPI/NFP events from FRED release dates within the horizon (``[]`` on failure)."""
    try:
        from core.external_data import fetch_fred_release_dates
    except Exception:
        return []

    today = date.today()
    end = today + timedelta(days=horizon_days)
    events: list[dict[str, str]] = []
    for release_id, label in _FRED_RELEASE_IDS.items():
        try:
            dates = fetch_fred_release_dates(release_id)
        except Exception:
            dates = []
        for ds in dates:
            try:
                evd = date.fromisoformat(ds)
            except ValueError:
                continue
            if today <= evd <= end:
                events.append({"date": ds, "event": label, "importance": "high"})
    return events


def _get_macro_events(horizon_days: int) -> list[dict[str, str]]:
    """Macro events: FRED-sourced CPI/NFP + static FOMC, static fallback offline.

    When FRED returns nothing (offline / no key / rate-limited) the full static
    schedule is used so the calendar never goes blank. Otherwise FRED supplies
    CPI/NFP (always current) and FOMC is taken from the static list since FRED
    has no FOMC release feed. Deduplicated by ``(date, event)``.
    """
    fred = _fred_macro_events(horizon_days)
    if not fred:
        return list(_SCHEDULED_MACRO_EVENTS)

    merged: dict[tuple[str, str], dict[str, str]] = {(e["date"], e["event"]): e for e in fred}
    for e in _SCHEDULED_MACRO_EVENTS:
        if e["event"] == "FOMC":
            merged[(e["date"], e["event"])] = e
    return list(merged.values())


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

    for item in _get_macro_events(horizon_days):
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
