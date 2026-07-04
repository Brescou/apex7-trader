"""Tests for dashboard/callbacks/analytics.py win-rate pairing.

Covers the Review Finding: _load_trades_db() orders rows
``ORDER BY timestamp DESC`` (most recent first). The win-rate calculation
filtered that DESC-ordered list down to prior_buys (buys of the same
symbol before this SELL, still DESC) and then picked prior_buys[-1] — the
LAST element of a DESC list is the OLDEST buy in the symbol's whole
history, not the one immediately preceding this specific sale. Every SELL
after the first ever BUY of a symbol was mispaired.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dashboard.server import RED


def _dash_collect_text(node) -> list[str]:
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


def _trade(ts: str, action: str, symbol: str, price: float, shares: float = 1.0) -> dict:
    return {
        "timestamp": ts,
        "symbol": symbol,
        "action": action,
        "price": price,
        "amount_usd": round(price * shares, 2),
        "shares": shares,
        "confidence": 0.7,
        "source": "simulation",
    }


@pytest.fixture()
def _synthetic_trades():
    """BUY@100 -> SELL@110 (+10%, a real win), then BUY@200 -> SELL@190
    (-5%, a real loss). Rows are returned DESC (most recent first), exactly
    as _load_trades_db() would. The correct win rate is 1/2 = 50%; the old
    bug (prior_buys[-1]) pairs the second SELL against the very first BUY
    (100.0) instead of its own BUY (200.0), reporting a fabricated +90%
    "win" and a 100% win rate.
    """
    return [
        _trade("2026-01-01T12:00:00", "SELL", "AAPL", 190.0),
        _trade("2026-01-01T11:00:00", "BUY", "AAPL", 200.0),
        _trade("2026-01-01T10:00:00", "SELL", "AAPL", 110.0),
        _trade("2026-01-01T09:00:00", "BUY", "AAPL", 100.0),
    ]


def test_win_rate_pairs_sell_with_the_immediately_preceding_buy(_synthetic_trades, tmp_db):
    from dashboard.callbacks.analytics import _analytics_refresh

    with patch("dashboard.callbacks.analytics._load_trades_db", return_value=_synthetic_trades):
        with patch("dashboard.callbacks.analytics._load_postmortem", return_value=[]):
            with patch("dashboard.callbacks.analytics._load_agent_memory", return_value=[]):
                result = _analytics_refresh(1, None, "analytics")

    text = " ".join(_dash_collect_text(result))
    assert "50.0%" in text, f"expected the real 50% win rate, got: {text}"
    assert "100.0%" not in text, "win rate must not be inflated to 100% by the mispaired SELL"
    assert "+90.00%" not in text, "the second SELL must not show a fabricated +90% best trade"
    assert "-5.00%" in text, "the second SELL's real -5% loss must appear as the worst trade"


def test_pnl_by_ticker_shows_real_gain_loss_not_gross_proceeds(tmp_db):
    """A losing trade (BUY 3 @ 100 -> SELL 3 @ 70, real P&L = -90) must
    render as a loss — the old code summed each SELL's gross amount_usd
    (210, always positive) instead of gain/loss, so a real loser always
    drew a green bar and bar_colors (red for negative) was dead code.
    """
    from dashboard.callbacks.analytics import _analytics_refresh

    trades = [
        _trade("2026-01-01T10:00:00", "SELL", "TSLA", 70.0, shares=3.0),
        _trade("2026-01-01T09:00:00", "BUY", "TSLA", 100.0, shares=3.0),
    ]

    with patch("dashboard.callbacks.analytics._load_trades_db", return_value=trades):
        with patch("dashboard.callbacks.analytics._load_postmortem", return_value=[]):
            with patch("dashboard.callbacks.analytics._load_agent_memory", return_value=[]):
                result = _analytics_refresh(1, None, "analytics")

    charts_row = result.children[2]
    pnl_by_ticker_fig = charts_row.children[0].figure
    bar = pnl_by_ticker_fig.data[0]

    assert list(bar.y) == ["TSLA"]
    assert bar.x[0] == pytest.approx(-90.0), f"expected real P&L -90, got {bar.x[0]}"
    assert bar.marker.color[0] == RED, "a real loss must render as a red bar"
