"""Tests for the partial-exit logic in ``arbitrate_node`` (Feature 2)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agents.multi import SIZING_TO_SELL_PCT, arbitrate_node


def _make_state(tech_action: str, tech_sell_pct: float | None, sizing: str) -> dict:
    """Build a minimal ``MultiAgentState`` snapshot for ``arbitrate_node``."""
    tech_vote = {
        "agent": "technician",
        "action": tech_action,
        "symbol": "AAPL",
        "confidence": 0.8,
    }
    if tech_sell_pct is not None:
        tech_vote["sell_pct"] = tech_sell_pct
    analyst_vote = {
        "agent": "analyst",
        "action": tech_action,
        "symbol": "AAPL",
        "confidence": 0.75,
    }
    risk_vote = {
        "agent": "risk_manager",
        "risk_score": 4,
        "max_safe_allocation_pct": 30.0,
        "sizing_recommendation": sizing,
    }
    macro_vote = {
        "agent": "macro_watcher",
        "market_regime": "transitional",
        "macro_bias": "neutral",
    }
    return {
        "round": 1,
        "agent_votes": [tech_vote, analyst_vote, risk_vote, macro_vote],
        "tech_vote": tech_vote,
        "analyst_vote": analyst_vote,
        "risk_vote": risk_vote,
        "macro_vote": macro_vote,
        "balance": 1000.0,
        "positions": {"AAPL": {"shares": 1.0, "avg_price": 100.0}},
        "prices": {"AAPL": 150.0},
        "skip_research": True,
    }


@pytest.mark.parametrize(
    "sizing,expected",
    [
        ("FULL", 100.0),
        ("HALF", 50.0),
        ("QUARTER", 25.0),
        ("SKIP", 0.0),
    ],
)
def test_sizing_maps_to_sell_pct(sizing: str, expected: float) -> None:
    state = _make_state("SELL", tech_sell_pct=None, sizing=sizing)
    out = arbitrate_node(state)
    assert out["decision"]["action"] == "SELL"
    assert out["decision"]["sell_pct"] == expected
    assert out["arbitration"]["sell_pct"] == expected


def test_sell_pct_takes_min_of_risk_and_tech() -> None:
    """If technician explicitly limits the exit, arbitrate uses the smaller value."""
    state = _make_state("SELL", tech_sell_pct=30, sizing="HALF")
    out = arbitrate_node(state)
    assert out["decision"]["sell_pct"] == 30.0


def test_buy_decision_keeps_default_sell_pct() -> None:
    """``sell_pct`` is irrelevant for BUY but stays at 100 for backward compat."""
    state = _make_state("BUY", tech_sell_pct=None, sizing="FULL")
    out = arbitrate_node(state)
    assert out["decision"]["sell_pct"] == 100.0


def test_unknown_sizing_falls_back_to_full() -> None:
    state = _make_state("SELL", tech_sell_pct=None, sizing="WHATEVER")
    out = arbitrate_node(state)
    assert out["decision"]["sell_pct"] == 100.0


def test_sizing_table_is_complete() -> None:
    """The mapping must cover every documented risk_manager sizing value."""
    assert set(SIZING_TO_SELL_PCT) == {"FULL", "HALF", "QUARTER", "SKIP"}
