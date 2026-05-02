"""Tests for ``evaluate_pending_trades`` (Feature 3.2).

The job reads ``pending_evaluations`` rows whose deadline has passed,
fetches the current spot price via yfinance ``fast_info`` (mocked here),
and writes ``was_correct`` (1/0/None) into matching ``agent_memory`` rows.
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.shared.nodes import evaluate_pending_trades


def _seed_pending(
    db_path,
    *,
    trade_id: int,
    trace_id: str,
    symbol: str,
    action: str,
    entry_price: float,
    eval_after: datetime,
) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO pending_evaluations "
            "(trade_id,trace_id,symbol,action,entry_price,entry_date,eval_after_date,evaluated) "
            "VALUES (?,?,?,?,?,?,?,0)",
            (
                trade_id,
                trace_id,
                symbol,
                action,
                entry_price,
                (eval_after - timedelta(days=7)).isoformat(),
                eval_after.isoformat(),
            ),
        )


def _seed_agent_memory(db_path, *, trace_id: str, agent_name: str = "technician") -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO agent_memory "
            "(timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source,trace_id) "
            "VALUES (?,?,?,?,?,NULL,NULL,'live',?)",
            ("2026-04-25T12:00:00", agent_name, "AAPL", "BUY", 0.8, trace_id),
        )


def _agent_memory_row(db_path, trace_id: str) -> dict:
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM agent_memory WHERE trace_id = ?", (trace_id,)).fetchall()
    return dict(rows[0]) if rows else {}


def _pending_row(db_path, trace_id: str) -> dict:
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM pending_evaluations WHERE trace_id = ?", (trace_id,)
        ).fetchall()
    return dict(rows[0]) if rows else {}


def test_buy_correct_when_price_rises(tmp_db) -> None:
    db = tmp_db
    trace = "tracebuy1"
    _seed_pending(
        db,
        trade_id=1,
        trace_id=trace,
        symbol="AAPL",
        action="BUY",
        entry_price=100.0,
        eval_after=datetime.now() - timedelta(hours=1),
    )
    _seed_agent_memory(db, trace_id=trace)

    with patch("agents.shared.eval._fast_last_price", return_value=110.0):  # +10% >>> 1% threshold
        n = evaluate_pending_trades()
    assert n == 1
    assert _agent_memory_row(db, trace)["was_correct"] == 1
    assert _pending_row(db, trace)["evaluated"] == 1


def test_buy_wrong_when_price_drops(tmp_db) -> None:
    db = tmp_db
    trace = "tracebuy2"
    _seed_pending(
        db,
        trade_id=2,
        trace_id=trace,
        symbol="AAPL",
        action="BUY",
        entry_price=100.0,
        eval_after=datetime.now() - timedelta(hours=1),
    )
    _seed_agent_memory(db, trace_id=trace)

    with patch("agents.shared.eval._fast_last_price", return_value=90.0):
        evaluate_pending_trades()
    assert _agent_memory_row(db, trace)["was_correct"] == 0


def test_sell_correct_when_price_drops(tmp_db) -> None:
    db = tmp_db
    trace = "tracesell1"
    _seed_pending(
        db,
        trade_id=3,
        trace_id=trace,
        symbol="AAPL",
        action="SELL",
        entry_price=100.0,
        eval_after=datetime.now() - timedelta(hours=1),
    )
    _seed_agent_memory(db, trace_id=trace, agent_name="analyst")

    with patch("agents.shared.eval._fast_last_price", return_value=90.0):
        evaluate_pending_trades()
    assert _agent_memory_row(db, trace)["was_correct"] == 1


def test_inconclusive_when_change_below_threshold(tmp_db) -> None:
    """Move smaller than 1% → was_correct stays NULL (inconclusive)."""
    db = tmp_db
    trace = "traceflat"
    _seed_pending(
        db,
        trade_id=4,
        trace_id=trace,
        symbol="AAPL",
        action="BUY",
        entry_price=100.0,
        eval_after=datetime.now() - timedelta(hours=1),
    )
    _seed_agent_memory(db, trace_id=trace)

    with patch("agents.shared.eval._fast_last_price", return_value=100.5):
        evaluate_pending_trades()
    assert _agent_memory_row(db, trace)["was_correct"] is None
    # Pending row IS marked evaluated even when the verdict is inconclusive,
    # so the job does not retry it forever.
    assert _pending_row(db, trace)["evaluated"] == 1


def test_skip_when_price_unavailable(tmp_db) -> None:
    """If fast_info returns None, leave the pending row for the next tick."""
    db = tmp_db
    trace = "traceskip"
    _seed_pending(
        db,
        trade_id=5,
        trace_id=trace,
        symbol="AAPL",
        action="BUY",
        entry_price=100.0,
        eval_after=datetime.now() - timedelta(hours=1),
    )
    _seed_agent_memory(db, trace_id=trace)

    with patch("agents.shared.eval._fast_last_price", return_value=None):
        evaluate_pending_trades()
    assert _agent_memory_row(db, trace)["was_correct"] is None
    assert _pending_row(db, trace)["evaluated"] == 0


def test_future_deadline_is_ignored(tmp_db) -> None:
    db = tmp_db
    trace = "tracefuture"
    _seed_pending(
        db,
        trade_id=6,
        trace_id=trace,
        symbol="AAPL",
        action="BUY",
        entry_price=100.0,
        eval_after=datetime.now() + timedelta(days=3),
    )
    _seed_agent_memory(db, trace_id=trace)

    with patch("agents.shared.eval._fast_last_price", return_value=200.0) as m:
        n = evaluate_pending_trades()
    assert n == 0
    m.assert_not_called()
    assert _pending_row(db, trace)["evaluated"] == 0
