"""Tests for the ``pending_evaluations`` workflow (Feature 3.1).

Verifies that ``save_memory_node`` defers ``was_correct`` to a pending row
keyed on the trade id, with an evaluation deadline ~ ``EVAL_HORIZON_DAYS``
trading days in the future (approximated as ``EVAL_HORIZON_CALENDAR_DAYS``).
"""

import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.shared.nodes import _sim_mode, make_save_memory_node
from config import EVAL_HORIZON_CALENDAR_DAYS
from core.data import Portfolio


def _build_state(action: str, symbol: str = "AAPL") -> dict:
    return {
        "decision": {
            "action": action,
            "symbol": symbol,
            "sell_pct": 100.0 if action == "SELL" else 100.0,
            "confidence": 0.8,
            "reasoning": "test",
        },
        "emotion": "FOCUSED",
        "prices": {symbol: 150.0},
        "known_patterns": [],
    }


def _seed_trade(p: Portfolio, action: str, symbol: str = "AAPL") -> None:
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


def _fetch_pending(db_path) -> list[dict]:
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT trade_id, trace_id, symbol, action, entry_price, "
            "entry_date, eval_after_date, evaluated FROM pending_evaluations"
        ).fetchall()
    return [dict(r) for r in rows]


def test_pending_evaluations_table_exists(tmp_db) -> None:
    with sqlite3.connect(tmp_db) as con:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' " "AND name='pending_evaluations'"
        ).fetchall()
    assert rows, "pending_evaluations table missing"


def test_save_memory_creates_pending_row_for_buy(tmp_db) -> None:
    _sim_mode["enabled"] = True
    p = Portfolio()
    _seed_trade(p, "BUY")
    make_save_memory_node(p)(_build_state("BUY"))

    pending = _fetch_pending(tmp_db)
    assert len(pending) == 1
    row = pending[0]
    assert row["action"] == "BUY"
    assert row["symbol"] == "AAPL"
    assert row["entry_price"] == 150.0
    assert row["evaluated"] == 0
    assert row["trade_id"] >= 1


def test_save_memory_creates_pending_row_for_sell(tmp_db) -> None:
    _sim_mode["enabled"] = True
    p = Portfolio()
    _seed_trade(p, "SELL")
    make_save_memory_node(p)(_build_state("SELL"))

    pending = _fetch_pending(tmp_db)
    assert len(pending) == 1
    assert pending[0]["action"] == "SELL"


def test_eval_deadline_matches_horizon(tmp_db) -> None:
    _sim_mode["enabled"] = True
    p = Portfolio()
    _seed_trade(p, "BUY")
    make_save_memory_node(p)(_build_state("BUY"))

    pending = _fetch_pending(tmp_db)[0]
    entry = datetime.fromisoformat(pending["entry_date"])
    deadline = datetime.fromisoformat(pending["eval_after_date"])
    assert (deadline - entry).days == EVAL_HORIZON_CALENDAR_DAYS


def test_save_memory_skips_pending_for_hold(tmp_db) -> None:
    _sim_mode["enabled"] = True
    p = Portfolio()
    make_save_memory_node(p)(_build_state("HOLD"))
    assert _fetch_pending(tmp_db) == []


def test_arbitrate_no_longer_writes_was_correct(tmp_db) -> None:
    """``arbitrate_node`` must NOT touch ``agent_memory.was_correct``."""
    from agents.multi import arbitrate_node

    _sim_mode["enabled"] = True
    # Seed an agent_memory row with NULL was_correct (as ``_record_vote`` does).
    with sqlite3.connect(tmp_db) as con:
        con.execute(
            "INSERT INTO agent_memory "
            "(timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source) "
            "VALUES (?,?,?,?,?,NULL,NULL,'simulation')",
            ("2026-05-01T12:00:00", "technician", "AAPL", "BUY", 0.8),
        )

    state = {
        "round": 1,
        "agent_votes": [
            {"agent": "technician", "action": "BUY", "symbol": "AAPL", "confidence": 0.8},
            {"agent": "analyst", "action": "BUY", "symbol": "AAPL", "confidence": 0.75},
            {
                "agent": "risk_manager",
                "risk_score": 4,
                "max_safe_allocation_pct": 30,
                "sizing_recommendation": "FULL",
            },
            {
                "agent": "macro_watcher",
                "market_regime": "transitional",
                "macro_bias": "neutral",
            },
        ],
        "tech_vote": {"agent": "technician", "action": "BUY", "symbol": "AAPL", "confidence": 0.8},
        "analyst_vote": {"agent": "analyst", "action": "BUY", "symbol": "AAPL", "confidence": 0.75},
        "risk_vote": {
            "agent": "risk_manager",
            "risk_score": 4,
            "max_safe_allocation_pct": 30,
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
    }
    arbitrate_node(state)

    with sqlite3.connect(tmp_db) as con:
        rows = con.execute(
            "SELECT was_correct FROM agent_memory WHERE agent_name='technician'"
        ).fetchall()
    assert rows and rows[0][0] is None, "was_correct should remain NULL after arbitrate"
