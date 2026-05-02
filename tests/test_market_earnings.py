"""Tests for earnings calendar helpers in ``market_data``."""

import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_fetch_earnings_calendar_from_dict() -> None:
    from market_data import fetch_earnings_calendar

    fixed = date(2030, 6, 15)
    mock_cal = {"Earnings Date": [fixed]}
    with patch("market_data.yf.Ticker") as T:
        T.return_value.calendar = mock_cal
        out = fetch_earnings_calendar(["ZZZ"])
    assert out["ZZZ"] is not None
    assert out["ZZZ"]["earnings_date"] == "2030-06-15"
    assert isinstance(out["ZZZ"]["days_until"], int)


def test_fetch_earnings_calendar_dataframe() -> None:
    import pandas as pd

    from market_data import fetch_earnings_calendar

    d = date(2030, 3, 1)
    df = pd.DataFrame([[d]], columns=["Earnings Date"])
    with patch("market_data.yf.Ticker") as T:
        T.return_value.calendar = df
        out = fetch_earnings_calendar(["QQQ"])
    assert out["QQQ"] is not None
    assert out["QQQ"]["earnings_date"] == "2030-03-01"


def test_is_earnings_week_window() -> None:
    from market_data import is_earnings_week

    near = date.today() + timedelta(days=3)
    with patch("market_data.yf.Ticker") as T:
        T.return_value.calendar = {"Earnings Date": [near]}
        assert is_earnings_week("NEAR") is True

    far = date.today() + timedelta(days=30)
    with patch("market_data.yf.Ticker") as T:
        T.return_value.calendar = {"Earnings Date": [far]}
        assert is_earnings_week("FAR") is False


def test_is_earnings_week_none_when_no_calendar() -> None:
    from market_data import is_earnings_week

    with patch("market_data.yf.Ticker") as T:
        T.return_value.calendar = None
        assert is_earnings_week("XXX") is False
