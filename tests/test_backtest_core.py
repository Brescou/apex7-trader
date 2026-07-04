"""Tests for core/backtest.py — Review Findings #1, #4, #5 (medium severity).

Covers: win_rate accounting for slippage/commission (not just raw price),
the final forced liquidation being recorded as a trade, and
compare_strategies sharing a single fetch instead of two independent
(fail-silent) ones.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest

from config import COMMISSION_PCT, SLIPPAGE_PCT
from core.backtest import _compute_metrics, _simulate, compare_strategies, compute_indicators


def _synthetic_df(n: int = 22, start: float = 185.0, step: float = 0.12) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    closes = [start + step * i for i in range(n)]
    return pd.DataFrame(
        {
            "Open": [c - 0.25 for c in closes],
            "High": [c + 0.35 for c in closes],
            "Low": [c - 0.45 for c in closes],
            "Close": closes,
            "Volume": [1_100_000] * n,
        },
        index=idx,
    )


def test_win_rate_accounts_for_slippage_and_commission():
    """A round trip barely profitable on raw price must count as a loss once
    slippage (both legs) and commission (both legs) are actually paid.
    """
    bp = 100.0
    # Raw move is +0.15% — positive, but slippage (2x0.05%) + commission
    # (2x0.1%) alone cost ~0.3%, so the realized trade is a net loss.
    sp = 100.15
    trades = [
        {"action": "BUY", "symbol": "AAPL", "price": bp},
        {"action": "SELL", "symbol": "AAPL", "price": sp},
    ]
    metrics = _compute_metrics([1000.0, 999.0], trades, 1000.0)
    assert metrics["win_rate"] == 0.0

    # Sanity: the raw (cost-free) move actually was positive, confirming
    # the test isolates the cost adjustment and not a mistaken direction.
    assert (sp - bp) / bp > 0


def test_win_rate_survives_a_genuinely_profitable_round_trip():
    trades = [
        {"action": "BUY", "symbol": "AAPL", "price": 100.0},
        {"action": "SELL", "symbol": "AAPL", "price": 110.0},
    ]
    metrics = _compute_metrics([1000.0, 1090.0], trades, 1000.0)
    assert metrics["win_rate"] == 100.0


def test_final_open_position_is_recorded_as_a_trade():
    """A position still open at the last bar must appear in the trades list
    as a SELL — otherwise it's invisible to win_rate/n_trades even though
    the equity curve already reflects its outcome.

    Price series: a sharp drop (drives RSI < 30, triggering a BUY) followed
    by a noisy-but-flat stretch (RSI recovers toward ~50, never crossing 70,
    so no organic SELL fires) — guarantees the position is still open at
    the end. A *perfectly* flat tail hits an RSI edge case (zero avg loss
    -> RSI pinned at 100 by convention), hence the small oscillation.
    """
    closes = [100.0 - 3.0 * i for i in range(15)]
    closes += [55.0 + (0.3 if i % 2 == 0 else -0.2) for i in range(20)]
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="D")
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 0.5 for c in closes],
            "Low": [c - 0.5 for c in closes],
            "Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )
    df = compute_indicators(df)

    trades, equity_curve = _simulate(df, "AAPL", "simple", 1000.0, 0.05)

    assert any(t["action"] == "BUY" for t in trades), f"test setup didn't trigger a BUY: {trades}"
    assert trades[-1]["action"] == "SELL"
    assert trades[-1]["reason"] == "period_end"
    assert len(equity_curve) > 1


def test_simulate_enriches_trades_with_bar_index_shares_and_pnl():
    """Review Finding: _simulate's trade dicts carried no bar_index/shares/
    pnl, forcing the dashboard to reconstruct them with wrong assumptions
    (INITIAL_BALANCE * 0.95 for shares, trade sequence number for the chart
    marker x-position). _simulate must expose these directly instead.
    """
    closes = [100.0 - 3.0 * i for i in range(15)]  # triggers a BUY (RSI < 30)
    closes += [55.0 + (0.3 if i % 2 == 0 else -0.2) for i in range(20)]  # holds to period_end
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="D")
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 0.5 for c in closes],
            "Low": [c - 0.5 for c in closes],
            "Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )
    df = compute_indicators(df)

    trades, equity_curve = _simulate(df, "AAPL", "simple", 1000.0, 0.05)

    sell = trades[-1]
    buy = trades[-2]  # the BUY that opened the position still open at period_end
    assert sell["action"] == "SELL" and sell["reason"] == "period_end"
    assert buy["action"] == "BUY"

    # bar_index must be the actual row position, not a trade sequence number.
    assert isinstance(buy["bar_index"], int)
    assert 0 <= buy["bar_index"] < len(df)
    assert sell["bar_index"] == len(df) - 1

    # shares must reflect the real allocation at that point (95% of the cash
    # on hand when this BUY fired / effective buy price), not a naive
    # INITIAL_BALANCE-based guess — matches the paired BUY exactly since
    # this position was never pyramided.
    assert buy["shares"] > 0
    assert sell["shares"] == buy["shares"]

    # pnl on the closing SELL must be the net dollar P&L vs the BUY's real
    # cost basis (which the dashboard used to reconstruct incorrectly).
    # cost_basis = alloc * (1 + COMMISSION_PCT), and shares = alloc /
    # (price * (1 + SLIPPAGE_PCT)), so cost_basis derives from shares/price.
    expected_cost_basis = buy["shares"] * buy["price"] * (1 + SLIPPAGE_PCT) * (1 + COMMISSION_PCT)
    assert sell["cost_basis"] == pytest.approx(expected_cost_basis, rel=1e-9)
    assert isinstance(sell["pnl"], float)
    assert buy["pnl"] is None


def test_compare_strategies_fetches_historical_data_exactly_once(monkeypatch):
    df = _synthetic_df()
    calls = []

    def _fake_fetch(symbol, period="6mo", interval="1d"):
        calls.append(symbol)
        return df.copy()

    with patch("core.backtest.fetch_historical", side_effect=_fake_fetch):
        with patch("core.backtest.yf.download", return_value=df.copy()):
            result = compare_strategies("AAPL", period="1mo")

    # Exactly one call for AAPL's own history — "simple" and "multi" share it.
    assert calls.count("AAPL") == 1
    assert result["simple"]["symbol"] == "AAPL"
    assert result["multi"]["symbol"] == "AAPL"


def test_compare_strategies_surfaces_error_on_insufficient_data(monkeypatch):
    empty_df = pd.DataFrame()

    with patch("core.backtest.fetch_historical", return_value=empty_df):
        result = compare_strategies("ZZZZ", period="1mo")

    assert "error" in result
    assert result["simple"]["n_trades"] == 0
    assert result["multi"]["n_trades"] == 0
