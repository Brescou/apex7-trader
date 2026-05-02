"""Pyramiding / position layering tests (Portfolio + risk_check)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.shared.nodes import risk_check_node
from core.data import Portfolio

_SYM = "AAPL"


def test_pyramid_buy_recalculates_avg() -> None:
    """Two equal-share adds at 150 and 130 → weighted average 140."""
    portfolio = Portfolio()
    assert portfolio.buy(_SYM, 150.0, 150.0)["success"]
    assert portfolio.buy(_SYM, 130.0, 130.0)["success"]
    assert abs(portfolio.positions[_SYM]["avg_price"] - 140.0) < 1e-6
    assert portfolio.positions[_SYM]["layers"] == 2


def test_pyramid_max_layers() -> None:
    """Three successful pyramid adds (layers 1→3), fourth buy rejected."""
    portfolio = Portfolio()
    assert portfolio.buy(_SYM, 300.0, 100.0)["success"]
    assert portfolio.buy(_SYM, 100.0, 100.0)["success"]
    assert portfolio.buy(_SYM, 100.0, 100.0)["success"]
    fourth = portfolio.buy(_SYM, 100.0, 100.0)
    assert fourth["success"] is False
    assert "max pyramid" in (fourth.get("error") or "").lower()


def test_pyramid_watermark_unchanged() -> None:
    """High watermark stays at first entry high after a lower pyramid add."""
    portfolio = Portfolio()
    portfolio.buy(_SYM, 150.0, 150.0)
    portfolio.buy(_SYM, 130.0, 130.0)
    assert portfolio.high_watermarks.get(_SYM) == 150.0


def test_pyramid_full_sell_clears_layers() -> None:
    """Full exit removes position and pyramid state."""
    portfolio = Portfolio()
    portfolio.buy(_SYM, 150.0, 150.0)
    portfolio.buy(_SYM, 130.0, 130.0)
    assert portfolio.sell(_SYM, 100.0, 140.0)["success"]
    assert _SYM not in portfolio.positions
    assert _SYM not in portfolio.high_watermarks


def test_pyramid_partial_sell_keeps_layers() -> None:
    """Partial sell reduces shares but preserves ``layers``."""
    portfolio = Portfolio()
    assert portfolio.buy(_SYM, 200.0, 100.0)["success"]
    assert portfolio.buy(_SYM, 100.0, 100.0)["success"]
    assert portfolio.positions[_SYM]["layers"] == 2
    assert portfolio.sell(_SYM, 50.0, 110.0)["success"]
    assert portfolio.positions[_SYM]["layers"] == 2


def test_pyramid_risk_check_alloc() -> None:
    """risk_check rejects pyramid BUY when existing + new alloc exceeds 1.5 × MAX_ALLOC_PCT."""
    sym = _SYM
    heavy = {
        "decision": {"action": "BUY", "symbol": sym, "allocation_pct": 10, "sell_pct": 100},
        "prices": {sym: 100.0},
        "positions": {sym: {"shares": 9.0, "avg_price": 100.0, "layers": 2}},
        "balance": 500.0,
    }
    out_fail = risk_check_node(heavy)
    assert out_fail["decision"].get("_risk_passed") is False
    assert "pyramidale" in (out_fail["decision"].get("_risk_reason") or "").lower()

    ok = {
        "decision": {"action": "BUY", "symbol": sym, "allocation_pct": 10, "sell_pct": 100},
        "prices": {sym: 100.0},
        "positions": {sym: {"shares": 1.0, "avg_price": 100.0, "layers": 1}},
        "balance": 5000.0,
    }
    out_ok = risk_check_node(ok)
    assert out_ok["decision"].get("_risk_passed") is True
