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

import pytest

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


def _seed_agent_memory(
    db_path, *, trace_id: str, agent_name: str = "technician", vote: str = "BUY"
) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO agent_memory "
            "(timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source,trace_id) "
            "VALUES (?,?,?,?,?,NULL,NULL,'live',?)",
            ("2026-04-25T12:00:00", agent_name, "AAPL", vote, 0.8, trace_id),
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
        with patch("agents.shared.eval.get_simulation_mode", return_value=False):
            with patch("core.notifications.alert_evaluation") as alert_ev:
                n = evaluate_pending_trades()
    assert n == 1
    assert _agent_memory_row(db, trace)["was_correct"] == 1
    assert _pending_row(db, trace)["evaluated"] == 1
    alert_ev.assert_called_once()
    call_kw = alert_ev.call_args.kwargs
    assert call_kw["symbol"] == "AAPL"
    assert call_kw["was_correct"] is True


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
    _seed_agent_memory(db, trace_id=trace, agent_name="analyst", vote="SELL")

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


def test_pending_row_not_marked_evaluated_when_verdict_write_fails(tmp_db) -> None:
    """If the ``agent_memory`` UPDATE fails (e.g. transient SQLite lock), the
    verdict never landed anywhere — marking ``pending_evaluations.evaluated``
    regardless would permanently lose it (no more retries, was_correct stays
    NULL forever). The row must stay ``evaluated = 0`` so the next tick
    retries the write.
    """
    db = tmp_db
    trace = "tracewritefail"
    _seed_pending(
        db,
        trade_id=8,
        trace_id=trace,
        symbol="AAPL",
        action="BUY",
        entry_price=100.0,
        eval_after=datetime.now() - timedelta(hours=1),
    )
    _seed_agent_memory(db, trace_id=trace)

    with patch("agents.shared.eval._fast_last_price", return_value=110.0):
        with patch("agents.shared.eval._db_write_at", return_value=False) as mock_write:
            n = evaluate_pending_trades()

    assert n == 0
    assert mock_write.called
    assert _agent_memory_row(db, trace)["was_correct"] is None
    assert _pending_row(db, trace)["evaluated"] == 0


def test_db_path_pinned_for_whole_run_even_if_mode_switches_mid_loop(tmp_path) -> None:
    """A mode switch (e.g. via POST /api/control/mode) happening while
    evaluate_pending_trades() is mid-loop must not route later writes to a
    different DB file than the SELECT that produced the rows — otherwise
    pending_evaluations/agent_memory rows get silently orphaned in the
    wrong file (Review Finding: _get_db_path() used to be re-resolved on
    every _db_read/_db_write call, with nothing pinning it for a batch).
    """
    import agents.shared.db as db_mod

    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"

    with patch.object(db_mod, "_get_db_path", return_value=db_a):
        db_mod._db_initialized_paths.discard(str(db_a))
        db_mod._ensure_db()

    trace = "tracepindrift"
    _seed_pending(
        db_a,
        trade_id=9,
        trace_id=trace,
        symbol="AAPL",
        action="BUY",
        entry_price=100.0,
        eval_after=datetime.now() - timedelta(hours=1),
    )
    _seed_agent_memory(db_a, trace_id=trace)

    switched = {"flag": False}

    def _flaky_path():
        return db_b if switched["flag"] else db_a

    def _price_then_switch(_symbol):
        # Simulates a mode switch landing exactly between the SELECT (which
        # produced this row) and the writes that resolve it.
        switched["flag"] = True
        return 110.0

    try:
        with patch.object(db_mod, "_get_db_path", side_effect=_flaky_path):
            with patch("agents.shared.eval._fast_last_price", side_effect=_price_then_switch):
                with patch("agents.shared.eval.get_simulation_mode", return_value=True):
                    n = evaluate_pending_trades()

        assert n == 1
        assert not db_b.exists(), "no write should ever have touched the post-switch DB file"
        assert _agent_memory_row(db_a, trace)["was_correct"] == 1
        assert _pending_row(db_a, trace)["evaluated"] == 1
    finally:
        db_mod._db_initialized_paths.discard(str(db_a))
        db_mod._db_initialized_paths.discard(str(db_b))


def test_evaluation_skips_discord_in_simulation_mode(tmp_db) -> None:
    """No ``alert_evaluation`` when ``get_simulation_mode()`` is true."""

    db = tmp_db
    trace = "tracesimskip"
    _seed_pending(
        db,
        trade_id=7,
        trace_id=trace,
        symbol="AAPL",
        action="BUY",
        entry_price=100.0,
        eval_after=datetime.now() - timedelta(hours=1),
    )
    _seed_agent_memory(db, trace_id=trace)

    with patch("agents.shared.eval._fast_last_price", return_value=110.0):
        with patch("agents.shared.eval.get_simulation_mode", return_value=True):
            with patch("core.notifications.alert_evaluation") as alert_ev:
                evaluate_pending_trades()
    assert _agent_memory_row(db, trace)["was_correct"] == 1
    alert_ev.assert_not_called()


def test_eval_pct_change_stores_absolute_magnitude_of_move(tmp_db) -> None:
    """``eval_pct_change`` must store the ABSOLUTE magnitude of the price
    move (not signed) — ``_compute_dynamic_weights`` uses it to weight
    accuracy by move size, magnitude-weighted. A coverage gap this suite
    never pinned down with an exact expected value for either BUY or SELL
    (Review Finding).
    """
    db = tmp_db

    trace_buy = "trace-pct-buy"
    _seed_pending(
        db,
        trade_id=10,
        trace_id=trace_buy,
        symbol="AAPL",
        action="BUY",
        entry_price=100.0,
        eval_after=datetime.now() - timedelta(hours=1),
    )
    _seed_agent_memory(db, trace_id=trace_buy)

    with patch("agents.shared.eval._fast_last_price", return_value=115.0):  # +15%
        with patch("agents.shared.eval.get_simulation_mode", return_value=False):
            with patch("core.notifications.alert_evaluation"):
                evaluate_pending_trades()

    buy_row = _agent_memory_row(db, trace_buy)
    assert buy_row["was_correct"] == 1
    assert buy_row["eval_pct_change"] == pytest.approx(0.15)

    trace_sell = "trace-pct-sell"
    _seed_pending(
        db,
        trade_id=11,
        trace_id=trace_sell,
        symbol="AAPL",  # _seed_agent_memory always inserts symbol="AAPL"
        action="SELL",
        entry_price=200.0,
        eval_after=datetime.now() - timedelta(hours=1),
    )
    _seed_agent_memory(db, trace_id=trace_sell, vote="SELL")

    with patch("agents.shared.eval._fast_last_price", return_value=170.0):  # -15%
        with patch("agents.shared.eval.get_simulation_mode", return_value=False):
            with patch("core.notifications.alert_evaluation"):
                evaluate_pending_trades()

    sell_row = _agent_memory_row(db, trace_sell)
    assert sell_row["was_correct"] == 1
    assert sell_row["eval_pct_change"] == pytest.approx(0.15), (
        "eval_pct_change must be the absolute magnitude — a SELL correctly "
        "predicting a price DROP must still store a positive move size"
    )
