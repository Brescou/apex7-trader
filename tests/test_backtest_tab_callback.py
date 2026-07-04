"""Tests for dashboard/callbacks/backtest_tab.py's use of _simulate's
enriched trade fields (bar_index/shares/pnl/cost_basis).

Covers two Review Findings that share the same root cause (core.backtest's
_simulate didn't expose bar_index/shares/pnl, forcing the dashboard to
reconstruct them with wrong assumptions):
- BUY/SELL chart markers were placed at the trade's sequence number
  instead of its actual bar index.
- The trade-log P&L was reconstructed assuming every BUY allocates 95% of
  the fixed INITIAL_BALANCE, instead of the real compounding cash amount
  _simulate actually used.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dash_collect_text(node) -> list[str]:
    """Flatten a Dash component tree into text fragments."""
    if node is None:
        return []
    if isinstance(node, str):
        return [node]
    if isinstance(node, (list, tuple)):
        out: list[str] = []
        for ch in node:
            out.extend(_dash_collect_text(ch))
        return out
    children = getattr(node, "children", None)
    if children is None:
        return []
    if isinstance(children, (list, tuple)):
        out: list[str] = []
        for ch in children:
            out.extend(_dash_collect_text(ch))
        return out
    return _dash_collect_text(children)


def _fake_result() -> dict:
    """A synthetic run_backtest() result with two round trips at different
    compounding cash levels — the second BUY allocates 95% of ~1190 (post
    first-trade cash), not 95% of the fixed INITIAL_BALANCE=1000. The old
    dashboard code's shares/P&L reconstruction only matched the *first*
    trade and diverged from here on.
    """
    return {
        "symbol": "AAPL",
        "period": "1mo",
        "strategy": "simple",
        "trades": [
            {
                "date": "2025-01-05",
                "action": "BUY",
                "symbol": "AAPL",
                "price": 100.0,
                "reason": "rsi_oversold",
                "bar_index": 5,
                "shares": 9.5,
                "pnl": None,
            },
            {
                "date": "2025-01-10",
                "action": "SELL",
                "symbol": "AAPL",
                "price": 120.0,
                "reason": "rsi_overbought",
                "bar_index": 10,
                "shares": 9.5,
                "pnl": 188.0,
                "cost_basis": 952.0,
            },
            {
                "date": "2025-01-15",
                "action": "BUY",
                "symbol": "AAPL",
                "price": 130.0,
                "reason": "rsi_oversold",
                "bar_index": 15,
                "shares": 8.32,
                "pnl": None,
            },
            {
                "date": "2025-01-20",
                "action": "SELL",
                "symbol": "AAPL",
                "price": 140.0,
                "reason": "period_end",
                "bar_index": 20,
                "shares": 8.32,
                "pnl": 79.0,
                "cost_basis": 1082.0,
            },
        ],
        "n_trades": 4,
        "equity_curve": [1000.0 + i * 5 for i in range(22)],
        "benchmark_return_pct": 3.0,
        "vs_benchmark": 2.0,
        "final_value": 1219.0,
        "total_return_pct": 21.9,
        "win_rate": 100.0,
        "max_drawdown_pct": 2.0,
        "sharpe_ratio": 1.5,
    }


def _run_callback():
    from dashboard.callbacks.backtest_tab import _backtest_run

    with patch("core.backtest.run_backtest", return_value=_fake_result()):
        with patch("core.backtest.walk_forward_backtest", side_effect=RuntimeError("no network")):
            return _backtest_run(1, "AAPL", "1mo", "simple")


def test_buy_sell_markers_use_real_bar_index_not_sequence_number():
    """The old code placed markers at (1, 2, 3, 4) — the trade's position in
    the list — instead of the bar they actually occurred at (6, 11, 16, 21
    once the +1 offset for equity_curve's leading initial-cash entry is
    applied).
    """
    result = _run_callback()
    graph = result.children[1]
    fig = graph.figure

    buy_trace = next(t for t in fig.data if t.name == "BUY")
    sell_trace = next(t for t in fig.data if t.name == "SELL")

    assert list(buy_trace.x) == [6, 16]
    assert list(sell_trace.x) == [11, 21]


def test_trade_log_uses_real_shares_and_pnl_not_a_fixed_balance_guess():
    """The old code assumed every BUY allocates 95% of INITIAL_BALANCE
    (1000) — for the second round trip this diverges from the real
    compounding shares (8.32) the simulation actually used.
    """
    result = _run_callback()
    trade_table = result.children[2]
    text = " ".join(_dash_collect_text(trade_table))

    assert "9.5000" in text  # first BUY/SELL pair's real shares
    assert "8.3200" in text  # second pair's real (compounding) shares
    assert "+188.00" in text  # first SELL's real net pnl
    assert "+79.00" in text  # second SELL's real net pnl
    # Old reconstruction would have used (1000*0.95)/100 = 9.5 for the FIRST
    # trade (coincidentally close) but (1000*0.95)/130 = 7.3077 for the
    # second — nowhere near the real 8.32 — so this string must be absent.
    assert "7.3077" not in text


def test_total_pnl_sums_the_real_per_trade_pnl():
    result = _run_callback()
    trade_table = result.children[2]
    text = " ".join(_dash_collect_text(trade_table))
    assert "+267.00" in text  # 188.00 + 79.00
