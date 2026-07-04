"""Tests for dashboard/controller.py::_reconcile_portfolio_state.

Covers the Review Finding: implied_cash was replayed from trades.db
without accounting for commission (Portfolio.buy()/sell() debit/credit
amount +/- commission, not amount alone — both legs pushed implied_cash
higher than real cash by the sum of every trade's commission), and
without scoping to the CURRENT portfolio "life" — trades.db is never
purged across a death+RESET cycle, so a prior life's trades used to get
replayed into this life's reconciliation, producing a bogus drift warning
(or masking a real one of similar magnitude).
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data import Portfolio  # noqa: E402
from dashboard.controller import _reconcile_portfolio_state  # noqa: E402


def _insert_trade(db_path, *, timestamp: str, action: str, amount_usd: float) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO trades (timestamp, symbol, action, price, amount_usd, shares) "
            "VALUES (?, 'AAPL', ?, 100.0, ?, 1.0)",
            (timestamp, action, amount_usd),
        )


def _logged_drift(caplog) -> float:
    """Parse the "drift $X.XX" figure out of the reconciliation log line
    (present at both INFO "OK" and WARNING levels) — a precise numeric
    check independent of the $5 warning threshold, since a single round
    trip's commission-accounting error is well under that threshold and
    would never trigger a WARNING either way.
    """
    for rec in caplog.records:
        if "drift $" in rec.message:
            return float(rec.message.split("drift $")[1].split(")")[0])
    raise AssertionError(f"no reconciliation log line found: {[r.message for r in caplog.records]}")


def test_reconcile_accounts_for_commission_on_both_legs(tmp_db, caplog):
    """A portfolio that only ever executed trades matching trades.db exactly
    (including commission) must reconcile to ~$0 drift — the pre-fix code
    omitted commission on both legs, inflating implied_cash above the real
    cash by the sum of every trade's commission on every reconciliation.
    """
    port = Portfolio()
    now = datetime.now()
    port.created_at = (now - timedelta(minutes=5)).isoformat()

    buy = port.buy("AAPL", 500.0, 100.0)
    assert buy["success"]
    sell = port.sell("AAPL", 100.0, 110.0)
    assert sell["success"]

    _insert_trade(tmp_db, timestamp=now.isoformat(), action="BUY", amount_usd=buy["amount"])
    _insert_trade(
        tmp_db,
        timestamp=(now + timedelta(seconds=1)).isoformat(),
        action="SELL",
        amount_usd=sell["amount"],
    )

    with caplog.at_level("INFO", logger="apex7.controller"):
        _reconcile_portfolio_state(port)

    assert _logged_drift(caplog) < 0.01


def test_reconcile_ignores_trades_from_a_prior_life(tmp_db, caplog):
    """A large trade recorded before this portfolio's created_at (i.e. from
    a life that already ended in death + RESET) must not be replayed into
    the current life's implied_cash — otherwise the old ledger contaminates
    the new life's reconciliation with a bogus drift warning.
    """
    port = Portfolio()
    now = datetime.now()
    port.created_at = now.isoformat()

    # A stale trade from a life that already ended — a $900 BUY with no
    # matching SELL would blow implied_cash far off port.cash if it were
    # (wrongly) replayed into this life's reconciliation.
    _insert_trade(
        tmp_db,
        timestamp=(now - timedelta(days=1)).isoformat(),
        action="BUY",
        amount_usd=900.0,
    )

    with caplog.at_level("WARNING", logger="apex7.controller"):
        _reconcile_portfolio_state(port)

    assert not any(
        "drift" in rec.message and "$" in rec.message for rec in caplog.records
    ), "a prior life's trade leaked into this life's reconciliation"


def test_reconcile_still_warns_on_a_genuine_drift_within_the_current_life(tmp_db, caplog):
    """Sanity check: the life-scoping/commission fixes must not silence a
    REAL drift that happens within the current life.
    """
    port = Portfolio()
    now = datetime.now()
    port.created_at = (now - timedelta(minutes=5)).isoformat()
    # port.cash stays at INITIAL_BALANCE (no trades actually executed on
    # this Portfolio instance), but trades.db claims a $900 BUY happened
    # inside this life's window — a genuine, unexplained divergence.
    _insert_trade(tmp_db, timestamp=now.isoformat(), action="BUY", amount_usd=900.0)

    with caplog.at_level("WARNING", logger="apex7.controller"):
        _reconcile_portfolio_state(port)

    assert any(
        "drift" in rec.message and "$" in rec.message for rec in caplog.records
    ), "a genuine within-life drift must still be reported"


def test_reconcile_no_trades_yet_is_silent(tmp_db, caplog):
    """An empty trades.db (fresh install, never traded) must not log
    anything — the ``if not rows: return`` early exit — a coverage gap
    this suite never exercised (Review Finding).
    """
    port = Portfolio()

    with caplog.at_level("INFO", logger="apex7.controller"):
        _reconcile_portfolio_state(port)

    assert not any("reconcil" in rec.message.lower() for rec in caplog.records)


def test_reconcile_falls_back_to_full_ledger_without_created_at(tmp_db, caplog):
    """Without a ``created_at`` attribute (e.g. an older Portfolio restored
    from a JSON state file predating that field), reconciliation must fall
    back to replaying the ENTIRE trades.db ledger rather than raising or
    silently skipping every row — a coverage gap this suite never
    exercised (Review Finding).
    """
    port = Portfolio()
    del port.created_at
    assert not hasattr(port, "created_at")

    now = datetime.now()
    _insert_trade(
        tmp_db, timestamp=(now - timedelta(days=30)).isoformat(), action="BUY", amount_usd=900.0
    )

    with caplog.at_level("WARNING", logger="apex7.controller"):
        _reconcile_portfolio_state(port)

    assert any(
        "drift" in rec.message and "$" in rec.message for rec in caplog.records
    ), "an old, no-created_at trade must still be replayed into reconciliation"
