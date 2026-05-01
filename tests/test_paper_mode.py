"""Tests for the new ``paper`` trading mode (Feature 4.1).

Paper = real prices (yfinance) + rule-based agents (no LLM) + ``trades_paper.db``.
"""

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import agents.shared.nodes as nodes
from agents.shared.nodes import (
    _no_llm_mode,
    get_paper_mode,
    get_runtime_mode,
    get_simulation_mode,
    make_save_memory_node,
    set_paper_mode,
    set_simulation_mode,
)
from core.data import Portfolio


@pytest.fixture(autouse=True)
def reset_modes():
    """Each test starts with both flags off."""
    nodes._sim_mode["enabled"] = False
    nodes._paper_mode["enabled"] = False
    yield
    nodes._sim_mode["enabled"] = True  # autouse ``sim_mode`` resets defaults
    nodes._paper_mode["enabled"] = False


# ── Mode toggles ────────────────────────────────────────────────────────────


def test_runtime_mode_default_live() -> None:
    assert get_runtime_mode() == "live"
    assert get_simulation_mode() is False
    assert get_paper_mode() is False


def test_set_paper_disables_sim(monkeypatch) -> None:
    monkeypatch.setattr(nodes, "_write_env_var", lambda *a, **kw: None)
    set_simulation_mode(True)
    assert get_runtime_mode() == "sim"
    set_paper_mode(True)
    assert get_paper_mode() is True
    assert get_simulation_mode() is False
    assert get_runtime_mode() == "paper"


def test_set_sim_disables_paper(monkeypatch) -> None:
    monkeypatch.setattr(nodes, "_write_env_var", lambda *a, **kw: None)
    set_paper_mode(True)
    assert get_runtime_mode() == "paper"
    set_simulation_mode(True)
    assert get_simulation_mode() is True
    assert get_paper_mode() is False
    assert get_runtime_mode() == "sim"


def test_no_llm_mode_helper() -> None:
    assert _no_llm_mode() is False
    nodes._paper_mode["enabled"] = True
    assert _no_llm_mode() is True
    nodes._paper_mode["enabled"] = False
    nodes._sim_mode["enabled"] = True
    assert _no_llm_mode() is True


# ── Database routing ────────────────────────────────────────────────────────


def test_db_path_routes_to_paper_db() -> None:
    nodes._paper_mode["enabled"] = True
    nodes._sim_mode["enabled"] = False
    assert Path(nodes._get_db_path()).name == "trades_paper.db"


def test_db_path_paper_takes_precedence_over_sim() -> None:
    """Paper wins if both are accidentally on (defensive)."""
    nodes._paper_mode["enabled"] = True
    nodes._sim_mode["enabled"] = True
    assert Path(nodes._get_db_path()).name == "trades_paper.db"


def test_db_path_routes_to_sim_db() -> None:
    nodes._paper_mode["enabled"] = False
    nodes._sim_mode["enabled"] = True
    assert Path(nodes._get_db_path()).name == "trades_sim.db"


def test_db_path_routes_to_live_db() -> None:
    assert Path(nodes._get_db_path()).name == "trades.db"


# ── End-to-end: trade in paper mode persists with source='paper' ────────────


def test_paper_trade_persists_with_paper_source(tmp_db) -> None:
    nodes._paper_mode["enabled"] = True
    nodes._sim_mode["enabled"] = False

    p = Portfolio()
    p.trade_history.append(
        {
            "time": "2026-05-01T12:00:00",
            "action": "BUY",
            "symbol": "AAPL",
            "shares": 0.5,
            "price": 150.0,
            "amount": 75.0,
        }
    )
    state = {
        "decision": {
            "action": "BUY",
            "symbol": "AAPL",
            "sell_pct": 100.0,
            "confidence": 0.8,
            "reasoning": "rule-based BUY",
        },
        "emotion": "FOCUSED",
        "prices": {"AAPL": 150.0},
        "known_patterns": [],
    }
    make_save_memory_node(p)(state)

    with sqlite3.connect(tmp_db) as con:
        rows = con.execute(
            "SELECT action, source, lesson FROM trades ORDER BY id DESC LIMIT 1"
        ).fetchall()
    assert rows
    action, source, lesson = rows[0]
    assert action == "BUY"
    assert source == "paper"
    assert "[PAPER]" in (lesson or "")
