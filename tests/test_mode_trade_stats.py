"""Tests for dashboard/callbacks/analytics.py::_mode_trade_stats.

Covers the Review Finding: the LIVE-vs-PAPER comparison panel tracked a
single float per symbol (buys[symbol] = price), overwritten on every
pyramided BUY layer and popped entirely on the first matching SELL. A
pyramided position's P&L was priced against only the LAST layer, and a
partial sell_pct < 100 exit consumed the whole entry — any later SELL of
the still-open remainder found nothing to pair against and was silently
dropped from the stats entirely.
"""

import os
import sqlite3
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dashboard.callbacks.analytics import _mode_trade_stats


def _insert(db_path, *, ts: str, symbol: str, action: str, price: float, shares: float) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO trades (timestamp, symbol, action, price, shares, portfolio_value_after) "
            "VALUES (?, ?, ?, ?, ?, 1000.0)",
            (ts, symbol, action, price, shares),
        )


def test_pyramid_and_partial_sell_both_close_correctly(tmp_db):
    """Two BUY layers (10sh@100, 10sh@120 -> weighted avg 110) followed by
    two partial SELLs (10sh@130, then the remaining 10sh@90). Both SELLs
    must be priced against the 110 weighted-average cost basis, and BOTH
    must appear as closed trades.
    """
    _insert(tmp_db, ts="2026-01-01T09:00:00", symbol="AAPL", action="BUY", price=100.0, shares=10.0)
    _insert(tmp_db, ts="2026-01-01T10:00:00", symbol="AAPL", action="BUY", price=120.0, shares=10.0)
    _insert(
        tmp_db, ts="2026-01-01T11:00:00", symbol="AAPL", action="SELL", price=130.0, shares=10.0
    )
    _insert(tmp_db, ts="2026-01-01T12:00:00", symbol="AAPL", action="SELL", price=90.0, shares=10.0)

    with patch("dashboard.callbacks.analytics.mode_db_path", return_value=tmp_db):
        stats = _mode_trade_stats("live")

    assert stats["closed"] == 2, "the second SELL must not be silently dropped"
    assert stats["n_trades"] == 4
    # avg_pnl = mean(+18.18%, -18.18%) = 0.0%
    assert stats["avg_pnl"] == pytest.approx(0.0, abs=0.1)
    assert stats["win_rate"] == pytest.approx(50.0, abs=0.1)
