"""Tests for the partial-exit logic in ``arbitrate_node`` (Feature 2).

Covers the sizing → ``sell_pct`` mapping, the ``min(risk, tech)`` rule,
the SKIP guard via ``risk_check_node``, and DB persistence of ``sell_pct``
in the ``trades`` table (uses the ``tmp_db`` fixture for isolation).
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

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


def _make_buy_state(*, symbol: str = "AAPL", in_position: bool) -> dict:
    """Minimal state that resolves to a BUY in simulation arbitration."""
    tech_vote = {
        "agent": "technician",
        "action": "BUY",
        "symbol": symbol,
        "confidence": 0.9,
    }
    analyst_vote = {
        "agent": "analyst",
        "action": "BUY",
        "symbol": symbol,
        "confidence": 0.85,
    }
    risk_vote = {
        "agent": "risk_manager",
        "risk_score": 4,
        "max_safe_allocation_pct": 30.0,
        "sizing_recommendation": "FULL",
    }
    macro_vote = {
        "agent": "macro_watcher",
        "market_regime": "transitional",
        "macro_bias": "neutral",
    }
    positions: dict = {}
    if in_position:
        positions = {symbol: {"shares": 2.0, "avg_price": 140.0, "layers": 1}}
    return {
        "round": 1,
        "agent_votes": [tech_vote, analyst_vote, risk_vote, macro_vote],
        "tech_vote": tech_vote,
        "analyst_vote": analyst_vote,
        "risk_vote": risk_vote,
        "macro_vote": macro_vote,
        "balance": 5000.0,
        "positions": positions,
        "prices": {symbol: 150.0},
        "skip_research": True,
    }


def test_arbitrate_pyramid_flag_and_confidence_discount(tmp_db) -> None:
    """BUY on an already-open symbol sets ``is_pyramid`` and lowers confidence ~20%.

    ``arbitrate_node`` persists ``cycle_states`` on every call — needs
    ``tmp_db`` so that write doesn't land in the project's real DB.
    """
    base = arbitrate_node(_make_buy_state(in_position=False))
    pyr = arbitrate_node(_make_buy_state(in_position=True))
    assert base["decision"]["action"] == "BUY"
    assert base["decision"]["is_pyramid"] is False
    assert pyr["decision"]["is_pyramid"] is True
    assert pyr["decision"]["confidence"] == pytest.approx(base["decision"]["confidence"] * 0.8)


def test_risk_check_earnings_week_damps_allocation(monkeypatch) -> None:
    """Earnings guard reduces BUY allocation (option B), without failing the check."""
    from agents.shared import nodes as nodes_mod

    monkeypatch.setattr(nodes_mod, "is_earnings_week", lambda _s: True)
    sym = "AAPL"
    state = {
        "decision": {"action": "BUY", "symbol": sym, "allocation_pct": 20.0, "sell_pct": 100},
        "prices": {sym: 100.0},
        "positions": {},
        "balance": 5000.0,
    }
    out = risk_check_node(state)
    assert out["decision"].get("_risk_passed") is True
    assert out["decision"]["allocation_pct"] == pytest.approx(13.0)


def test_risk_check_allows_pyramid_buy_under_cap() -> None:
    """Existing position + layers below max + cumulative allocation ≤ 1.5 × MAX → PASS."""
    sym = "AAPL"
    state = {
        "decision": {"action": "BUY", "symbol": sym, "allocation_pct": 10, "sell_pct": 100},
        "prices": {sym: 100.0},
        "positions": {sym: {"shares": 1.0, "avg_price": 100.0, "layers": 1}},
        "balance": 5000.0,
    }
    out = risk_check_node(state)
    assert out["decision"].get("_risk_passed") is True


def test_risk_check_rejects_max_pyramid_layers(monkeypatch) -> None:
    from agents.shared import nodes as nodes_mod

    monkeypatch.setattr(nodes_mod, "MAX_PYRAMID_LAYERS", 2)
    sym = "AAPL"
    state = {
        "decision": {"action": "BUY", "symbol": sym, "allocation_pct": 5, "sell_pct": 100},
        "prices": {sym: 100.0},
        "positions": {sym: {"shares": 1.0, "avg_price": 100.0, "layers": 2}},
        "balance": 5000.0,
    }
    out = risk_check_node(state)
    assert out["decision"].get("_risk_passed") is False
    assert "pyramid" in (out["decision"].get("_risk_reason") or "").lower()


def test_risk_check_rejects_pyramid_over_alloc_cap() -> None:
    """existing_alloc + new alloc must not exceed MAX_ALLOC_PCT * 1.5."""
    sym = "AAPL"
    # ~64 % already in the symbol; +10 % new → above 60 % cap (40 * 1.5)
    state = {
        "decision": {"action": "BUY", "symbol": sym, "allocation_pct": 10, "sell_pct": 100},
        "prices": {sym: 100.0},
        "positions": {sym: {"shares": 9.0, "avg_price": 100.0, "layers": 1}},
        "balance": 500.0,
    }
    out = risk_check_node(state)
    assert out["decision"].get("_risk_passed") is False
    assert "pyramidale" in (out["decision"].get("_risk_reason") or "").lower()


def test_risk_check_rejects_buy_at_zero_price() -> None:
    """symbol in prices with a 0.0 quote must fail closed, not PASS a BUY
    that portfolio.buy() would then silently reject.
    """
    sym = "AAPL"
    state = {
        "decision": {"action": "BUY", "symbol": sym, "allocation_pct": 10, "sell_pct": 100},
        "prices": {sym: 0.0},
        "positions": {},
        "balance": 5000.0,
    }
    out = risk_check_node(state)
    assert out["decision"].get("_risk_passed") is False
    assert "prix invalide" in (out["decision"].get("_risk_reason") or "").lower()


def test_risk_check_rejects_buy_at_nan_price() -> None:
    sym = "AAPL"
    state = {
        "decision": {"action": "BUY", "symbol": sym, "allocation_pct": 10, "sell_pct": 100},
        "prices": {sym: float("nan")},
        "positions": {},
        "balance": 5000.0,
    }
    out = risk_check_node(state)
    assert out["decision"].get("_risk_passed") is False


def test_risk_check_rejects_sell_with_missing_price() -> None:
    """A position exists but the symbol's quote isn't in state["prices"]
    (e.g. yfinance dropped it this tick) — must fail closed, not PASS a
    SELL that portfolio.sell() would then silently reject at price=0.
    """
    sym = "AAPL"
    state = {
        "decision": {"action": "SELL", "symbol": sym, "sell_pct": 100},
        "prices": {},
        "positions": {sym: {"shares": 1.0, "avg_price": 100.0}},
        "balance": 1000.0,
    }
    out = risk_check_node(state)
    assert out["decision"].get("_risk_passed") is False
    assert "prix invalide" in (out["decision"].get("_risk_reason") or "").lower()


def test_risk_check_rejects_sell_at_zero_price() -> None:
    sym = "AAPL"
    state = {
        "decision": {"action": "SELL", "symbol": sym, "sell_pct": 100},
        "prices": {sym: 0.0},
        "positions": {sym: {"shares": 1.0, "avg_price": 100.0}},
        "balance": 1000.0,
    }
    out = risk_check_node(state)
    assert out["decision"].get("_risk_passed") is False


# ── Sizing → sell_pct mapping ────────────────────────────────────────────────


def test_arbitrate_full_sell(tmp_db) -> None:
    out = arbitrate_node(_make_state(sizing="FULL"))
    assert out["decision"]["action"] == "SELL"
    assert out["decision"]["sell_pct"] == 100.0


def test_arbitrate_half_sell(tmp_db) -> None:
    out = arbitrate_node(_make_state(sizing="HALF"))
    assert out["decision"]["sell_pct"] == 50.0


def test_arbitrate_quarter_sell(tmp_db) -> None:
    out = arbitrate_node(_make_state(sizing="QUARTER"))
    assert out["decision"]["sell_pct"] == 25.0


def test_arbitrate_skip_sell(tmp_db) -> None:
    """SKIP is a BUY-sizing signal ("commit no new capital") — it must never
    neuter an already-decided SELL down to a 0% no-op exit, exactly when the
    risk_manager judges conditions worst and exiting matters most. The SELL
    proceeds at full size (capped only by the technician's own sell_pct), and
    the downstream risk gate passes it through.
    """
    state = _make_state(sizing="SKIP")
    arb_out = arbitrate_node(state)
    assert arb_out["decision"]["sell_pct"] == 100.0

    # Drive the risk gate with the resulting decision.
    state_after = {**state, **arb_out}
    risk_out = risk_check_node(state_after)
    decision_post = risk_out["decision"]
    assert decision_post.get("_risk_passed") is True


def test_sell_pct_min_of_risk_and_tech(tmp_db) -> None:
    """If technician restricts the exit, arbitrate uses the smaller value."""
    out = arbitrate_node(_make_state(sizing="HALF", tech_sell_pct=25))
    assert out["decision"]["sell_pct"] == 25.0


# ── DB persistence ──────────────────────────────────────────────────────────


def test_sell_pct_persisted_in_db(tmp_db) -> None:
    """``save_memory_node`` writes ``sell_pct`` into the ``trades`` row."""
    _sim_mode["enabled"] = True  # skip Anthropic LLM lesson call

    portfolio = Portfolio()
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
        "execution_result": {"success": True, "shares": 0.25, "price": 150.0, "amount": 37.5},
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
