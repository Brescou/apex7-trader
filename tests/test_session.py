"""Tests for NYSE/TSX cash-session gating (core/session.py)."""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.session import is_cash_session_open

_ET = ZoneInfo("America/New_York")


def test_open_weekday_mid_session():
    now = datetime(2026, 8, 19, 10, 0, tzinfo=_ET)  # Wednesday
    assert is_cash_session_open(now)


def test_closed_before_open():
    now = datetime(2026, 8, 19, 9, 29, tzinfo=_ET)
    assert not is_cash_session_open(now)


def test_open_at_bell():
    now = datetime(2026, 8, 19, 9, 30, tzinfo=_ET)
    assert is_cash_session_open(now)


def test_closed_at_close_bell():
    now = datetime(2026, 8, 19, 16, 0, tzinfo=_ET)
    assert not is_cash_session_open(now)


def test_closed_weekend():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=_ET)  # Saturday
    assert not is_cash_session_open(now)


def test_naive_datetime_treated_as_eastern():
    now = datetime(2026, 8, 19, 11, 0)
    assert is_cash_session_open(now)
