"""End-to-end tests for the deferred ``was_correct`` workflow (Feature 3).

Mocks ``yfinance.Ticker.fast_info`` so the evaluation job never hits the
network, and uses the ``tmp_db`` fixture for SQLite isolation.
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import agents.multi as multi_mod
from agents.shared.nodes import _sim_mode, evaluate_pending_trades, make_save_memory_node
from agents.multi import WEIGHTS, _compute_dynamic_weights
from core.data import Portfolio


# ── Fixtures helpers ────────────────────────────────────────────────────────


def _ensure_trace_id_column(db_path) -> None:
    """Soft-add the ``trace_id`` column on ``agent_memory`` if missing."""
    with sqlite3.connect(db_path) as con:
        cols = {row[1] for row in con.execute("PRAGMA table_info(agent_memory)").fetchall()}
        if "trace_id" not in cols:
            con.execute("ALTER TABLE agent_memory ADD COLUMN trace_id TEXT")


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


def _was_correct(db_path, trace_id: str) -> int | None:
    with sqlite3.connect(db_path) as con:
        row = con.execute(
            "SELECT was_correct FROM agent_memory WHERE trace_id = ?", (trace_id,)
        ).fetchone()
    return row[0] if row else None


def _pending_evaluated(db_path, trace_id: str) -> int:
    with sqlite3.connect(db_path) as con:
        row = con.execute(
            "SELECT evaluated FROM pending_evaluations WHERE trace_id = ?", (trace_id,)
        ).fetchone()
    return int(row[0]) if row else -1


class _FakeFastInfo(dict):
    """yfinance ``fast_info`` exposes both ``.last_price`` and ``["lastPrice"]``."""

    def __init__(self, price: float | None) -> None:
        super().__init__()
        if price is not None:
            self["lastPrice"] = price
        self.last_price = price


def _mock_ticker(price: float | None):
    """Return a ``patch`` that replaces ``yfinance.Ticker`` with a counted stub.

    The replacement is a ``MagicMock`` whose ``return_value`` carries a
    ``fast_info`` attribute, so call assertions like ``mock.assert_not_called``
    keep working.
    """
    from unittest.mock import MagicMock

    stub = MagicMock(name="Ticker")
    stub.return_value.fast_info = _FakeFastInfo(price)
    return patch("agents.shared.nodes.yf.Ticker", stub)


def _due_yesterday() -> datetime:
    return datetime.now() - timedelta(hours=1)


@pytest.fixture(autouse=True)
def reset_weights_cache():
    """Ensure each test starts with an empty dynamic-weights cache."""
    multi_mod._cached_weights = {}
    multi_mod._weights_computed_at = 0.0
    yield
    multi_mod._cached_weights = {}
    multi_mod._weights_computed_at = 0.0


# ── 1. Trade creates pending evaluation ─────────────────────────────────────


def test_trade_creates_pending_evaluation(tmp_db) -> None:
    _sim_mode["enabled"] = True
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
            "reasoning": "test",
        },
        "emotion": "FOCUSED",
        "prices": {"AAPL": 150.0},
        "known_patterns": [],
    }
    make_save_memory_node(p)(state)

    with sqlite3.connect(tmp_db) as con:
        rows = con.execute("SELECT action, symbol, evaluated FROM pending_evaluations").fetchall()
    assert len(rows) == 1
    action, symbol, evaluated = rows[0]
    assert (action, symbol, evaluated) == ("BUY", "AAPL", 0)


# ── 2. was_correct stays NULL right after trade ─────────────────────────────


def test_was_correct_not_set_immediately(tmp_db) -> None:
    """Inserting an agent_memory row with NULL ``was_correct`` must remain NULL."""
    _ensure_trace_id_column(tmp_db)
    _seed_agent_memory(tmp_db, trace_id="t-fresh")

    assert _was_correct(tmp_db, "t-fresh") is None


# ── 3-7. Evaluation outcomes ────────────────────────────────────────────────


def _setup_eval(db_path, trace: str, action: str, entry: float) -> None:
    _ensure_trace_id_column(db_path)
    _seed_pending(
        db_path,
        trade_id=1,
        trace_id=trace,
        symbol="AAPL",
        action=action,
        entry_price=entry,
        eval_after=_due_yesterday(),
    )
    _seed_agent_memory(db_path, trace_id=trace)


def test_evaluate_buy_correct(tmp_db) -> None:
    _setup_eval(tmp_db, "t-buy-ok", "BUY", 100.0)
    with _mock_ticker(110.0):
        evaluate_pending_trades()
    assert _was_correct(tmp_db, "t-buy-ok") == 1
    assert _pending_evaluated(tmp_db, "t-buy-ok") == 1


def test_evaluate_buy_incorrect(tmp_db) -> None:
    _setup_eval(tmp_db, "t-buy-ko", "BUY", 100.0)
    with _mock_ticker(90.0):
        evaluate_pending_trades()
    assert _was_correct(tmp_db, "t-buy-ko") == 0


def test_evaluate_sell_correct(tmp_db) -> None:
    _setup_eval(tmp_db, "t-sell-ok", "SELL", 100.0)
    with _mock_ticker(85.0):
        evaluate_pending_trades()
    assert _was_correct(tmp_db, "t-sell-ok") == 1


def test_evaluate_sell_incorrect(tmp_db) -> None:
    _setup_eval(tmp_db, "t-sell-ko", "SELL", 100.0)
    with _mock_ticker(115.0):
        evaluate_pending_trades()
    assert _was_correct(tmp_db, "t-sell-ko") == 0


def test_evaluate_inconclusive(tmp_db) -> None:
    """Move below the 1 % significance threshold → was_correct stays NULL."""
    _setup_eval(tmp_db, "t-flat", "BUY", 100.0)
    with _mock_ticker(100.5):
        evaluate_pending_trades()
    assert _was_correct(tmp_db, "t-flat") is None
    # Pending row IS marked evaluated to avoid infinite retries on flat moves.
    assert _pending_evaluated(tmp_db, "t-flat") == 1


# ── 8. Future deadline is ignored ───────────────────────────────────────────


def test_evaluate_skips_future_dates(tmp_db) -> None:
    _ensure_trace_id_column(tmp_db)
    _seed_pending(
        tmp_db,
        trade_id=99,
        trace_id="t-future",
        symbol="AAPL",
        action="BUY",
        entry_price=100.0,
        eval_after=datetime.now() + timedelta(days=3),
    )
    _seed_agent_memory(tmp_db, trace_id="t-future")

    with _mock_ticker(200.0) as ticker_mock:
        n = evaluate_pending_trades()
    assert n == 0
    ticker_mock.assert_not_called()
    assert _was_correct(tmp_db, "t-future") is None
    assert _pending_evaluated(tmp_db, "t-future") == 0


# ── 9. Dynamic weights without evaluated history ────────────────────────────


def test_dynamic_weights_no_history(tmp_db) -> None:
    """Without any evaluated vote, ``_compute_dynamic_weights`` returns static weights."""
    out = _compute_dynamic_weights()
    assert out == WEIGHTS
    assert sum(out.values()) == pytest.approx(1.0)
