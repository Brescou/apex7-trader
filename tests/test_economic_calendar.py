"""Tests for the FRED-backed economic calendar (fallback + merge)."""

import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.external_data as ext  # noqa: E402
import market_data.economic_calendar as ec  # noqa: E402


def test_get_macro_events_fallback_to_static_when_fred_empty():
    with patch.object(ec, "_fred_macro_events", return_value=[]):
        events = ec._get_macro_events(120)
    assert events == ec._SCHEDULED_MACRO_EVENTS


def test_get_macro_events_merges_fred_cpi_nfp_with_static_fomc():
    soon = (date.today() + timedelta(days=10)).isoformat()
    fred = [{"date": soon, "event": "CPI", "importance": "high"}]
    with patch.object(ec, "_fred_macro_events", return_value=fred):
        events = ec._get_macro_events(120)
    # FRED CPI present
    assert any(e["event"] == "CPI" and e["date"] == soon for e in events)
    # FOMC carried over from the static list
    assert any(e["event"] == "FOMC" for e in events)


def test_fred_macro_events_filters_horizon():
    today = date.today()
    in_window = (today + timedelta(days=5)).isoformat()
    out_window = (today + timedelta(days=400)).isoformat()

    def _fake_release_dates(release_id, *a, **k):
        # only CPI (id 10) returns dates; NFP returns none
        return [in_window, out_window] if release_id == 10 else []

    with patch.object(ext, "fetch_fred_release_dates", side_effect=_fake_release_dates):
        events = ec._fred_macro_events(120)
    dates = {e["date"] for e in events}
    assert in_window in dates
    assert out_window not in dates


def test_build_rows_uses_fred_events():
    soon = (date.today() + timedelta(days=7)).isoformat()
    fred = [{"date": soon, "event": "NFP", "importance": "high"}]
    with patch.object(ec, "_get_macro_events", return_value=fred):
        with patch.object(ec, "fetch_earnings_calendar", return_value={}):
            rows = ec.build_economic_calendar_rows(["AAPL"], horizon_days=120)
    macro_rows = [r for r in rows if r["kind"] == "macro"]
    assert len(macro_rows) == 1
    assert macro_rows[0]["event"] == "NFP"
    assert macro_rows[0]["event_date"] == date.fromisoformat(soon)


def test_static_fomc_dates_match_the_real_2026_schedule():
    """The static list is merged into the calendar even when FRED is up, so
    its FOMC dates are the only source of truth (FRED has no FOMC release
    feed) — they must match the Fed's actual published 2026 meeting
    calendar (announcement day = 2nd day of each 2-day meeting):
    Jan 27-28, Mar 17-18, Apr 28-29, Jun 16-17, Jul 28-29, Sep 15-16,
    Oct 27-28, Dec 8-9. A stale/wrong FOMC date silently misleads the
    macro-watcher agent and the terminal's economic calendar.
    """
    fomc_dates = sorted(e["date"] for e in ec._SCHEDULED_MACRO_EVENTS if e["event"] == "FOMC")
    assert fomc_dates == [
        "2026-01-28",
        "2026-03-18",
        "2026-04-29",
        "2026-06-17",
        "2026-07-29",
        "2026-09-16",
        "2026-10-28",
        "2026-12-09",
    ]


def test_static_macro_events_are_chronologically_sorted():
    """A copy-paste error (e.g. wrong month) tends to also break ordering —
    guard against the list silently drifting out of chronological order.
    """
    dates = [e["date"] for e in ec._SCHEDULED_MACRO_EVENTS]
    assert dates == sorted(dates)


def test_fetch_fred_release_dates_parses_and_filters():
    ext._fred_release_cache.clear()
    today = date.today()
    past = (today - timedelta(days=10)).isoformat()
    future = (today + timedelta(days=10)).isoformat()
    payload = {"release_dates": [{"date": past}, {"date": future}, {"date": today.isoformat()}]}
    with patch.object(ext, "_http_get_json", return_value=payload):
        out = ext.fetch_fred_release_dates(10, max_cache_sec=0)
    assert past not in out
    assert future in out
    assert today.isoformat() in out
