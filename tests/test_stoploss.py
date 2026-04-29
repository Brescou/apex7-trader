"""Regression tests for execute_node stop-loss guards (Finding 3.1 / 5.4)."""

import math
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.shared.nodes import make_execute_node
from core.data import Portfolio


def _portfolio_aapl_10_at_150() -> Portfolio:
    """Portfolio with 10 AAPL @ $150 avg (synthetic, bypasses ``buy`` limits)."""
    p = Portfolio()
    with p._lock:
        p.positions["AAPL"] = {"shares": 10.0, "avg_price": 150.0}
        p.cash = 400.0
    return p


def _hold_state(prices: dict[str, float]) -> dict:
    """Minimal state for ``execute_node`` on HOLD."""
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


def test_stoploss_ignores_zero_price(caplog):
    """Quote at 0 must not trigger a destructive stop-loss (Finding 3.1)."""
    import logging

    p = _portfolio_aapl_10_at_150()
    execute = make_execute_node(p)
    with caplog.at_level(logging.WARNING):
        out = execute(_hold_state({"AAPL": 0.0}))

    assert out["alive"] is True
    assert "AAPL" in p.positions
    assert p.positions["AAPL"]["shares"] == 10.0
    assert p.positions["AAPL"]["avg_price"] == 150.0
    assert "Skipping stop-loss for AAPL" in caplog.text


def test_stoploss_triggers_on_real_drop():
    """Realistic drop below ``STOP_LOSS_PCT`` triggers liquidation."""
    p = _portfolio_aapl_10_at_150()
    execute = make_execute_node(p)

    with patch("agents.shared.nodes.STOP_LOSS_PCT", 0.2):
        out = execute(_hold_state({"AAPL": 100.0}))

    assert out["alive"] is True
    assert "AAPL" not in p.positions
    assert any("STOP-LOSS triggered" in e.get("message", "") for e in out["log"])


def test_stoploss_ignores_nan(caplog):
    """NaN quote must hit the guard (not the penny-stock branch)."""
    import logging

    p = _portfolio_aapl_10_at_150()
    execute = make_execute_node(p)
    with caplog.at_level(logging.WARNING):
        out = execute(_hold_state({"AAPL": float("nan")}))

    assert out["alive"] is True
    assert "AAPL" in p.positions
    assert p.positions["AAPL"]["shares"] == 10.0
    assert not any(math.isnan(x) for x in (p.cash, p.positions["AAPL"]["shares"]))
    assert "Skipping stop-loss for AAPL" in caplog.text
