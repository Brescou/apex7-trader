"""Trailing stop-loss vs high watermark (execute_node)."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.shared.nodes import make_execute_node
from core.data import Portfolio


def _hold_state(prices: dict[str, float]) -> dict:
    return {
        "decision": {
            "action": "HOLD",
            "symbol": "",
            "allocation_pct": 0,
            "sell_pct": 100,
            "reasoning": "test",
            "confidence": 0.5,
        },
        "prices": prices,
    }


def test_trailing_stop_after_peak_drawdown(tmp_db) -> None:
    """Liquidate when price falls far enough below the stored high watermark.

    A real trailing-stop fire persists a ``trades`` row (Batch B) — needs
    ``tmp_db`` so that write doesn't land in the project's real trades.db.
    """
    portfolio = Portfolio()
    with portfolio._lock:
        portfolio.positions["AAPL"] = {"shares": 10.0, "avg_price": 100.0}
        portfolio.high_watermarks["AAPL"] = 200.0
        portfolio.cash = 500.0
    execute = make_execute_node(portfolio)
    with patch("agents.shared.nodes.STOP_LOSS_PCT", 0.2):
        out = execute(_hold_state({"AAPL": 150.0}))
    assert out["alive"] is True
    assert "AAPL" not in portfolio.positions
    assert any("[TRAILING STOP]" in e.get("message", "") for e in out["log"])


def test_trailing_stop_not_triggered_below_threshold(tmp_db) -> None:
    """No exit when drawdown from high is below STOP_LOSS_PCT.

    This position is also +70% vs avg_price, which clears TAKE_PROFIT_PCT —
    the take-profit guard fires and persists a ``trades`` row (Batch B),
    hence ``tmp_db`` even though the trailing stop itself doesn't trigger.
    """
    portfolio = Portfolio()
    with portfolio._lock:
        portfolio.positions["AAPL"] = {"shares": 10.0, "avg_price": 100.0}
        portfolio.high_watermarks["AAPL"] = 200.0
        portfolio.cash = 500.0
    execute = make_execute_node(portfolio)
    with patch("agents.shared.nodes.STOP_LOSS_PCT", 0.2):
        out = execute(_hold_state({"AAPL": 170.0}))
    assert "AAPL" in portfolio.positions
    assert not any("[TRAILING STOP]" in e.get("message", "") for e in out["log"])


def test_update_watermarks_raises_peak() -> None:
    """High watermark tracks the running maximum quote."""
    portfolio = Portfolio()
    with portfolio._lock:
        portfolio.positions["MSFT"] = {"shares": 1.0, "avg_price": 50.0}
        portfolio.high_watermarks["MSFT"] = 50.0
    portfolio.update_watermarks({"MSFT": 60.0})
    assert portfolio.high_watermarks["MSFT"] == 60.0
    portfolio.update_watermarks({"MSFT": 55.0})
    assert portfolio.high_watermarks["MSFT"] == 60.0
