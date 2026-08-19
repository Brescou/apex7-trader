"""NYSE / TSX regular-session clock (cash hours).

Both venues trade 09:30–16:00 America/New_York on weekdays. LIVE/PAPER
agent cycles skip LLM calls outside this window; SIM is not gated here.
US listings follow NYSE holidays, which this helper does **not** encode —
weekends + clock only.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_OPEN_MIN = 9 * 60 + 30  # 09:30
_CLOSE_MIN = 16 * 60  # 16:00 (exclusive)


def is_cash_session_open(now: datetime | None = None) -> bool:
    """Return True during weekday NYSE/TSX regular hours (09:30–16:00 ET).

    Args:
        now: Instant to evaluate. Naive datetimes are treated as Eastern.
            ``None`` uses the current time.
    """
    if now is None:
        et = datetime.now(_ET)
    elif now.tzinfo is None:
        et = now.replace(tzinfo=_ET)
    else:
        et = now.astimezone(_ET)

    if et.weekday() >= 5:
        return False
    minutes = et.hour * 60 + et.minute
    return _OPEN_MIN <= minutes < _CLOSE_MIN
