"""Lightweight tests to cover isolated modules (coverage toward CI threshold)."""

import os
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_seed_live_price_history_uses_yfinance() -> None:
    """Seeding pulls daily rows and sets technician history (network-free)."""
    import pandas as pd

    import agents.shared.nodes as nodes
    from agents.shared.watchlist import get_watchlist

    idx = pd.date_range("2026-01-01", periods=20, freq="D")
    df = pd.DataFrame({"Close": [100.0 + i * 0.1 for i in range(20)]}, index=idx)
    with patch("agents.shared.nodes.yf.download", return_value=df):
        nodes._live_price_history.clear()
        nodes._last_price_date.clear()
        nodes._live_price_history_seeded = False
        nodes._seed_live_price_history()
    try:
        assert nodes._live_price_history_seeded
        for sym in get_watchlist():
            assert len(nodes._live_price_history.get(sym, [])) >= 1
    finally:
        nodes._live_price_history.clear()
        nodes._last_price_date.clear()
        nodes._live_price_history_seeded = False


def test_seed_live_price_history_retries_when_every_download_fails() -> None:
    """If every symbol's download fails (e.g. yfinance rate-limited at
    startup), the seed must NOT be marked done — otherwise the technician's
    RSI stays permanently blind (50.0, insufficient data) instead of
    retrying on the next cycle (Review Finding).
    """
    import agents.shared.nodes as nodes

    def _boom(*_a, **_k):
        raise RuntimeError("rate limited")

    with patch("agents.shared.nodes.yf.download", side_effect=_boom):
        nodes._live_price_history.clear()
        nodes._last_price_date.clear()
        nodes._live_price_history_seeded = False
        nodes._seed_live_price_history()
    try:
        assert nodes._live_price_history_seeded is False
        assert nodes._live_price_history == {}
    finally:
        nodes._live_price_history.clear()
        nodes._last_price_date.clear()
        nodes._live_price_history_seeded = False


class _PausingDict(dict):
    """Pauses on its first ``setdefault()`` call so a test can force a
    second writer to attempt entry while the first is mid-mutation.
    """

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.entered = threading.Event()
        self.release = threading.Event()
        self._first = True

    def setdefault(self, key, default=None):
        if self._first:
            self._first = False
            self.entered.set()
            self.release.wait(timeout=2.0)
        return super().setdefault(key, default)


def test_record_live_prices_for_rsi_serializes_concurrent_writers() -> None:
    """_record_live_prices_for_rsi() runs inside fetch_data_node once per
    cycle, but technician_node reads the same _live_price_history dict
    concurrently during the parallel specialist fan-out (Send). The
    mutating loop (setdefault/append/reassign-on-trim) must run under
    _live_price_history_lock — the same lock _seed_live_price_history()
    already uses — or a concurrent caller can hit a dict-changed-size-
    during-iteration race or a half-written list (Review Finding).
    """
    import datetime as real_datetime

    import agents.shared.nodes as nodes

    tuesday = real_datetime.date(2026, 5, 5)  # a known weekday — the
    # weekend guard (a separate Review Finding fix) would otherwise skip
    # the write entirely and this test would depend on which day it runs.
    assert tuesday.weekday() < 5

    paused = _PausingDict()
    orig_history, orig_dates, orig_seeded = (
        nodes._live_price_history,
        nodes._last_price_date,
        nodes._live_price_history_seeded,
    )
    nodes._live_price_history = paused
    nodes._last_price_date = {}
    nodes._live_price_history_seeded = True  # skip seeding entirely
    try:
        with patch("agents.shared.nodes.date") as mock_date:
            mock_date.today.return_value = tuesday

            thread_a = threading.Thread(
                target=lambda: nodes._record_live_prices_for_rsi({"AAPL": 100.0})
            )
            thread_a.start()
            assert paused.entered.wait(timeout=2.0), "thread A never reached setdefault"

            # Thread A is now paused inside the mutating loop, still holding
            # _live_price_history_lock. A second writer for a DIFFERENT
            # symbol must block on the lock instead of racing ahead.
            thread_b = threading.Thread(
                target=lambda: nodes._record_live_prices_for_rsi({"MSFT": 200.0})
            )
            thread_b.start()
            thread_b.join(timeout=0.3)
            assert thread_b.is_alive(), "a second writer must block on the lock, not race ahead"
            assert "MSFT" not in paused

            paused.release.set()
            thread_a.join(timeout=2.0)
            thread_b.join(timeout=2.0)

        assert "AAPL" in paused
        assert "MSFT" in paused
    finally:
        nodes._live_price_history = orig_history
        nodes._last_price_date = orig_dates
        nodes._live_price_history_seeded = orig_seeded


def test_record_live_prices_for_rsi_skips_weekends() -> None:
    """Markets are closed on weekends — the live quote just echoes Friday's
    last trade, so appending on a Saturday/Sunday would inject a
    duplicate, zero-change "close" into the RSI window every weekend,
    skewing the rolling calculation (Review Finding).
    """
    import datetime as real_datetime

    import agents.shared.nodes as nodes

    saturday = real_datetime.date(2026, 5, 9)  # a known Saturday
    assert saturday.weekday() == 5

    orig_history, orig_dates, orig_seeded = (
        nodes._live_price_history,
        nodes._last_price_date,
        nodes._live_price_history_seeded,
    )
    nodes._live_price_history = {}
    nodes._last_price_date = {}
    nodes._live_price_history_seeded = True  # skip seeding entirely
    try:
        with patch("agents.shared.nodes.date") as mock_date:
            mock_date.today.return_value = saturday
            nodes._record_live_prices_for_rsi({"AAPL": 100.0})

        assert nodes._live_price_history.get("AAPL", []) == [], (
            "must not append a weekend close into the RSI history — got "
            f"{nodes._live_price_history.get('AAPL')!r}"
        )
        assert "AAPL" not in nodes._last_price_date
    finally:
        nodes._live_price_history = orig_history
        nodes._last_price_date = orig_dates
        nodes._live_price_history_seeded = orig_seeded
