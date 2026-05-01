"""End-to-end tests for the paper trading mode (Feature 4.3).

These cover the contract:
    paper = real prices (yfinance) + rule-based decisions (no LLM) +
            ``trades_paper.db`` + live cadence (``AGENT_INTERVAL``).
"""

import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import agents.multi as multi_mod
import agents.shared.nodes as nodes
from agents.shared.nodes import (
    get_paper_mode,
    get_runtime_mode,
    get_simulation_mode,
    make_fetch_data_node,
    make_save_memory_node,
    set_paper_mode,
    set_simulation_mode,
)
from config import AGENT_INTERVAL
from core.data import Portfolio


@pytest.fixture(autouse=True)
def reset_modes(monkeypatch):
    """Each test starts with every mode flag off; ``.env`` writes are silenced."""
    monkeypatch.setattr(nodes, "_write_env_var", lambda *a, **kw: None)
    nodes._sim_mode["enabled"] = False
    nodes._paper_mode["enabled"] = False
    yield
    nodes._sim_mode["enabled"] = True  # autouse ``sim_mode`` defaults
    nodes._paper_mode["enabled"] = False


def _seed_trade(p: Portfolio, action: str = "BUY", symbol: str = "AAPL") -> None:
    p.trade_history.append(
        {
            "time": "2026-05-01T12:00:00",
            "action": action,
            "symbol": symbol,
            "shares": 0.5,
            "price": 150.0,
            "amount": 75.0,
        }
    )


def _make_state(action: str = "BUY", symbol: str = "AAPL") -> dict:
    return {
        "decision": {
            "action": action,
            "symbol": symbol,
            "sell_pct": 100.0,
            "confidence": 0.8,
            "reasoning": "rule-based",
        },
        "emotion": "FOCUSED",
        "prices": {symbol: 150.0},
        "known_patterns": [],
    }


# ── 1. fetch_data uses real prices (yfinance), not the random walk ──────────


def test_paper_mode_uses_real_prices() -> None:
    """In paper mode, ``fetch_data_node`` must follow the live data path."""
    nodes._paper_mode["enabled"] = True

    p = Portfolio()
    state = {
        "positions": {},
        "prices": {},
        "balance": 1000.0,
    }

    # Stub the live fetch path; sim_fetch_data must NOT be hit.
    fake_data = ({"AAPL": 200.0}, "news string", {"AAPL": 0.1})
    with (
        patch("agents.shared.nodes.sim_fetch_data") as sim_mock,
        patch(
            "agents.shared.nodes._gather_data",
            new_callable=MagicMock,
            return_value=None,
        ),
        patch("agents.shared.nodes._run_async", return_value=fake_data),
    ):
        out = make_fetch_data_node(p)(state)

    sim_mock.assert_not_called()
    assert out["prices"] == {"AAPL": 200.0}
    assert "news string" in out["news"]


# ── 2. No Anthropic call anywhere in paper mode ──────────────────────────────


def test_paper_mode_no_llm_calls() -> None:
    """``_llm`` must never be invoked while a node runs under paper mode."""
    nodes._paper_mode["enabled"] = True

    state = {
        "round": 1,
        "agent_votes": [],
        "tech_vote": {"agent": "technician", "action": "HOLD", "symbol": "", "confidence": 0.5},
        "analyst_vote": {"agent": "analyst", "action": "HOLD", "symbol": "", "confidence": 0.5},
        "risk_vote": {
            "agent": "risk_manager",
            "risk_score": 4,
            "max_safe_allocation_pct": 30.0,
            "sizing_recommendation": "FULL",
        },
        "macro_vote": {
            "agent": "macro_watcher",
            "market_regime": "transitional",
            "macro_bias": "neutral",
        },
        "balance": 1000.0,
        "positions": {},
        "prices": {"AAPL": 150.0},
        "skip_research": True,
        "news": "",
        "sentiment": {"AAPL": 0.0},
    }

    with patch("agents.multi._llm") as multi_llm, patch("agents.shared.nodes._llm") as nodes_llm:
        multi_mod.supervisor_node(state)
        multi_mod.technician_node(state)
        multi_mod.analyst_node(state)
        multi_mod.risk_manager_node(state)
        multi_mod.macro_watcher_node(state)
        multi_mod.arbitrate_node(state)

    multi_llm.assert_not_called()
    nodes_llm.assert_not_called()


# ── 3. Trades land in trades_paper.db ───────────────────────────────────────


def test_paper_mode_separate_db() -> None:
    """``_get_db_path()`` must point at ``trades_paper.db`` while paper is on."""
    nodes._paper_mode["enabled"] = True
    assert Path(nodes._get_db_path()).name == "trades_paper.db"

    nodes._paper_mode["enabled"] = False
    assert Path(nodes._get_db_path()).name == "trades.db"


# ── 4. Persisted trades carry source='paper' ────────────────────────────────


def test_paper_mode_source_tag(tmp_db) -> None:
    nodes._paper_mode["enabled"] = True

    p = Portfolio()
    _seed_trade(p, "BUY")
    make_save_memory_node(p)(_make_state("BUY"))

    with sqlite3.connect(tmp_db) as con:
        rows = con.execute("SELECT action, source FROM trades ORDER BY id DESC LIMIT 1").fetchall()
    assert rows
    action, source = rows[0]
    assert action == "BUY"
    assert source == "paper"


# ── 5. Mode setters are mutually exclusive ──────────────────────────────────


def test_mode_mutual_exclusion() -> None:
    set_paper_mode(True)
    assert get_paper_mode() is True
    assert get_simulation_mode() is False
    assert get_runtime_mode() == "paper"

    set_simulation_mode(True)
    assert get_simulation_mode() is True
    assert get_paper_mode() is False
    assert get_runtime_mode() == "sim"

    set_paper_mode(True)
    assert get_paper_mode() is True
    assert get_simulation_mode() is False


# ── 6. Cycle cadence is AGENT_INTERVAL, not 3s, in paper mode ───────────────


def test_paper_mode_uses_live_interval() -> None:
    """Reproduce the controller's ``sleep_s`` decision under paper mode."""
    nodes._paper_mode["enabled"] = True
    nodes._sim_mode["enabled"] = False

    sleep_s = 3 if get_simulation_mode() else AGENT_INTERVAL
    assert sleep_s == AGENT_INTERVAL
    assert sleep_s != 3
