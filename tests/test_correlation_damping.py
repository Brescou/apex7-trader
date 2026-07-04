"""Test for Review Finding: correlation damping recalculates the action
score but not the symbol/sell_pct, so a BUY->SELL flip could target the
wrong ticker.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agents.multi import arbitrate_node


def _state() -> dict:
    """Technician votes BUY(GOOGL, conf=1.0) [weight 0.28 -> score 0.28],
    Analyst votes SELL(TSLA, conf=0.85) [weight 0.32 -> score 0.272].
    BUY wins pre-damping (0.28 > 0.272). Correlation damping (BUY x0.75)
    drops it to 0.21 < 0.272, flipping the winner to SELL.
    """
    votes = [
        {
            "agent": "technician",
            "action": "BUY",
            "confidence": 1.0,
            "symbol": "GOOGL",
            "key_indicators": [],
            "sell_pct": 100,
        },
        {
            "agent": "analyst",
            "action": "SELL",
            "confidence": 0.85,
            "symbol": "TSLA",
            "catalysts": [],
            "sentiment_score": -0.3,
        },
        {
            "agent": "risk_manager",
            "action": "HOLD",
            "confidence": 0.5,
            "risk_score": 3,
            "sizing_recommendation": "FULL",
            "max_safe_allocation_pct": 20,
            "var_1d": 0.01,
        },
        {
            "agent": "macro_watcher",
            "action": "HOLD",
            "confidence": 0.5,
            "market_regime": "neutral",
            "macro_bias": "neutral",
            "macro_score": 0.0,
        },
        {
            "agent": "economist",
            "action": "HOLD",
            "confidence": 0.5,
            "economic_score": 0.0,
        },
        {
            "agent": "geopolitician",
            "action": "HOLD",
            "confidence": 0.5,
            "geopolitical_risk": 3.0,
        },
    ]
    return {
        "agent_votes": votes,
        "agent_role": "",
        "supervisor_brief": "",
        "tech_vote": None,
        "analyst_vote": None,
        "risk_vote": None,
        "macro_vote": None,
        "arbitration": None,
        "decision": None,
        "round": 1,
        "positions": {"MSFT": {"shares": 5.0, "avg_price": 300.0}},
        "balance": 1000.0,
        "skip_research": True,
        "confidence": 0.0,
        "emotion": "CALM",
        "thoughts": "",
    }


@pytest.fixture(autouse=True)
def _reset_weights_cache():
    import agents.multi as multi_mod

    multi_mod._cached_weights = None
    multi_mod._weights_computed_at = 0.0
    yield
    multi_mod._cached_weights = None
    multi_mod._weights_computed_at = 0.0


def test_correlation_flip_retargets_symbol_to_the_new_action(tmp_db):
    with patch("agents.multi._portfolio_correlation", return_value=0.9):
        result = arbitrate_node(_state())

    decision = result["decision"]
    assert decision["action"] == "SELL", "damping should have flipped BUY -> SELL"
    assert decision["symbol"] == "TSLA", (
        "symbol must be re-derived for the new winning action, not left as "
        f"the old BUY target: got {decision['symbol']!r}"
    )


def test_correlation_log_still_names_the_original_buy_target(tmp_db):
    """The warning log should describe what actually triggered the damping
    (the correlated BUY candidate), even though the final decision moved on.
    """
    with patch("agents.multi._portfolio_correlation", return_value=0.9):
        result = arbitrate_node(_state())

    msgs = [e["message"] for e in result["log"]]
    assert any("CORRELATION RISK" in m and "GOOGL" in m for m in msgs)
