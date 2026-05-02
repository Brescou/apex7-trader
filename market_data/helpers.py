"""Helpers internes (sentiment, dates) pour ``market_data``."""

from datetime import date, datetime
from typing import Any

import pandas as pd


def format_age(ts: int) -> str:
    """Format a Unix timestamp as 'Xm ago', 'Xh ago', or 'Xd ago'."""
    try:
        delta = datetime.now() - datetime.fromtimestamp(ts)
        total_seconds = int(delta.total_seconds())
        if total_seconds < 3600:
            return f"{max(1, total_seconds // 60)}m ago"
        elif total_seconds < 86400:
            return f"{total_seconds // 3600}h ago"
        else:
            return f"{total_seconds // 86400}d ago"
    except Exception:
        return "?"


_POSITIVE_WORDS = {
    "beat",
    "surge",
    "gain",
    "rise",
    "up",
    "record",
    "strong",
    "rally",
    "soar",
    "top",
}
_NEGATIVE_WORDS = {
    "miss",
    "drop",
    "fall",
    "loss",
    "down",
    "weak",
    "cut",
    "warning",
    "crash",
    "decline",
    "sell",
}


def classify_sentiment(title: str) -> str:
    """Keyword-based sentiment bucket for a headline."""
    words = set(title.lower().split())
    pos = len(words & _POSITIVE_WORDS)
    neg = len(words & _NEGATIVE_WORDS)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def extract_next_earnings_raw(calendar: Any) -> Any:
    """Pull the next earnings date field from yfinance ``calendar`` (dict or DataFrame)."""
    if calendar is None:
        return None
    if isinstance(calendar, dict):
        ed = calendar.get("Earnings Date")
        if ed is None:
            return None
        if isinstance(ed, (list, tuple)):
            return ed[0] if len(ed) > 0 else None
        return ed
    try:
        cal_df = calendar
        if getattr(cal_df, "empty", True):
            return None
        return cal_df.iloc[0, 0]
    except Exception:
        return None


def coerce_to_date(value: Any) -> date | None:
    """Normalize yfinance / pandas date-like values to ``datetime.date``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        try:
            return value.date()
        except Exception:
            return None
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().date()
        except Exception:
            return None
    return None
