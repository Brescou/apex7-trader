"""Tests for the partial-exit logic in ``arbitrate_node`` (Feature 2).

Covers the sizing → ``sell_pct`` mapping, the ``min(risk, tech)`` rule,
the SKIP guard via ``risk_check_node``, and DB persistence of ``sell_pct``
in the ``trades`` table (uses the ``tmp_db`` fixture for isolation).
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.multi import arbitrate_node
from agents.shared.nodes import (
    _sim_mode,
    make_save_memory_node,
    risk_check_node,
)
from core.data import Portfolio


def _make_state(
    *,
    tech_action: str = "SELL",
    tech_sell_pct: float | None = None,
    sizing: str = "FULL",
    symbol: str = "AAPL",
) -> dict:
    """Build a minimal ``MultiAgentState`` snapshot for ``arbitrate_node``."""
    tech_vote = {
        "agent": "technician",
        "action": tech_action,
        "symbol": symbol,
        "confidence": 0.8,
    }
    if tech_sell_pct is not None:
        tech_vote["sell_pct"] = tech_sell_pct
    analyst_vote = {
        "agent": "analyst",
        "action": tech_action,
        "symbol": symbol,
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
        "positions": {symbol: {"shares": 1.0, "avg_price": 100.0}},
        "prices": {symbol: 150.0},
        "skip_research": True,
    }


# ── Sizing → sell_pct mapping ────────────────────────────────────────────────


def test_arbitrate_full_sell() -> None:
    out = arbitrate_node(_make_state(sizing="FULL"))
    assert out["decision"]["action"] == "SELL"
    assert out["decision"]["sell_pct"] == 100.0


def test_arbitrate_half_sell() -> None:
    out = arbitrate_node(_make_state(sizing="HALF"))
    assert out["decision"]["sell_pct"] == 50.0


def test_arbitrate_quarter_sell() -> None:
    out = arbitrate_node(_make_state(sizing="QUARTER"))
    assert out["decision"]["sell_pct"] == 25.0


def test_arbitrate_skip_sell() -> None:
    """SKIP → sell_pct=0 → ``risk_check_node`` rejects the trade.

    The arbitration still emits a SELL decision, but the downstream risk gate
    fails (``0 < sell_pct <= 100``), so ``execute_node`` is bypassed by the
    ``_risk_passed = False`` flag.
    """
    state = _make_state(sizing="SKIP")
    arb_out = arbitrate_node(state)
    assert arb_out["decision"]["sell_pct"] == 0.0

    # Drive the risk gate with the resulting decision.
    state_after = {**state, **arb_out}
    risk_out = risk_check_node(state_after)
    decision_post = risk_out["decision"]
    assert decision_post.get("_risk_passed") is False
    assert "sell_pct" in (decision_post.get("_risk_reason") or "")


def test_sell_pct_min_of_risk_and_tech() -> None:
    """If technician restricts the exit, arbitrate uses the smaller value."""
    out = arbitrate_node(_make_state(sizing="HALF", tech_sell_pct=25))
    assert out["decision"]["sell_pct"] == 25.0


# ── DB persistence ──────────────────────────────────────────────────────────


def test_sell_pct_persisted_in_db(tmp_db) -> None:
    """``save_memory_node`` writes ``sell_pct`` into the ``trades`` row."""
    _sim_mode["enabled"] = True  # skip Anthropic LLM lesson call

    portfolio = Portfolio()
    # Pretend a SELL just happened so ``last_trade`` lookup succeeds.
    portfolio.trade_history.append(
        {
            "time": "2026-05-01T12:00:00",
            "action": "SELL",
            "symbol": "AAPL",
            "shares": 0.25,
            "price": 150.0,
            "amount": 37.5,
        }
    )

    decision = {
        "action": "SELL",
        "symbol": "AAPL",
        "sell_pct": 25.0,
        "confidence": 0.78,
        "reasoning": "RSI overbought, taking partial profits",
    }
    state = {
        "decision": decision,
        "emotion": "FOCUSED",
        "prices": {"AAPL": 150.0},
        "known_patterns": [],
    }

    save_memory = make_save_memory_node(portfolio)
    save_memory(state)

    with sqlite3.connect(tmp_db) as con:
        rows = con.execute(
            "SELECT action, symbol, sell_pct FROM trades ORDER BY id DESC LIMIT 1"
        ).fetchall()
    assert rows, "trades row not inserted"
    action, symbol, sell_pct = rows[0]
    assert action == "SELL"
    assert symbol == "AAPL"
    assert sell_pct == 25.0
