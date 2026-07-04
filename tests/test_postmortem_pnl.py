"""Tests for Review Finding: postmortem PnL was computed against the LAST
BUY in trade_history (searched from the end of the whole list), not the
real entry — wrong for a pyramided position (should be the weighted
average across layers) and outright wrong for a same-day re-entry (a
later, unrelated BUY could get matched to an earlier SELL).
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agents.multi import (
    _reconstruct_avg_entry,
    _rolling_7d_closed_sell_pnls,
    _today_realized_pnl_pcts,
    run_daily_postmortem,
)
from core.data import Portfolio


def _trade(t: str, action: str, symbol: str, shares: float, price: float) -> dict:
    return {"time": t, "action": action, "symbol": symbol, "shares": shares, "price": price}


def test_simple_buy_then_sell():
    history = [
        _trade("2026-01-01T10:00:00", "BUY", "AAPL", 10.0, 100.0),
    ]
    entry = _reconstruct_avg_entry(history, "AAPL", datetime.fromisoformat("2026-01-02T10:00:00"))
    assert entry is not None
    price, buy_time = entry
    assert price == 100.0
    assert buy_time == datetime.fromisoformat("2026-01-01T10:00:00")


def test_pyramid_layers_produce_weighted_average():
    """Two BUY layers at different prices must blend into a share-weighted
    average, not just report the last layer's price.
    """
    history = [
        _trade("2026-01-01T10:00:00", "BUY", "AAPL", 10.0, 100.0),  # $1000
        _trade("2026-01-01T12:00:00", "BUY", "AAPL", 10.0, 120.0),  # $1200
    ]
    entry = _reconstruct_avg_entry(history, "AAPL", datetime.fromisoformat("2026-01-02T10:00:00"))
    assert entry is not None
    price, buy_time = entry
    # (1000 + 1200) / 20 shares = 110.0
    assert price == 110.0
    assert buy_time == datetime.fromisoformat("2026-01-01T10:00:00")  # first layer, for duration


def test_same_day_reentry_does_not_match_the_wrong_cycle():
    """buy1 -> sell1 (full close) -> buy2 -> sell2. Reconstructing the entry
    for sell1 must use buy1 (100.0), not buy2 (200.0) — the bug this
    guards against picked whichever BUY was most recent in the *entire*
    history, regardless of which sell it actually belonged to.
    """
    history = [
        _trade("2026-01-01T09:00:00", "BUY", "AAPL", 10.0, 100.0),
        _trade("2026-01-01T10:00:00", "SELL", "AAPL", 10.0, 105.0),
        _trade("2026-01-01T11:00:00", "BUY", "AAPL", 5.0, 200.0),
        _trade("2026-01-01T12:00:00", "SELL", "AAPL", 5.0, 210.0),
    ]

    entry_for_sell1 = _reconstruct_avg_entry(
        history, "AAPL", datetime.fromisoformat("2026-01-01T10:00:00")
    )
    assert entry_for_sell1 is not None
    assert entry_for_sell1[0] == 100.0, (
        f"sell1's entry must be buy1 (100.0), got {entry_for_sell1[0]} "
        "(the old bug would have picked buy2's 200.0)"
    )

    entry_for_sell2 = _reconstruct_avg_entry(
        history, "AAPL", datetime.fromisoformat("2026-01-01T12:00:00")
    )
    assert entry_for_sell2 is not None
    assert entry_for_sell2[0] == 200.0


def test_partial_sell_reduces_open_basis_proportionally():
    """buy 10 @ 100 -> partial sell 4 (60% remains) -> full sell of the
    remaining 6. The second sell's entry must still be 100.0 (same basis,
    just fewer shares), and the reconstruction shouldn't blow up.
    """
    history = [
        _trade("2026-01-01T09:00:00", "BUY", "AAPL", 10.0, 100.0),
        _trade("2026-01-01T10:00:00", "SELL", "AAPL", 4.0, 110.0),
    ]
    entry = _reconstruct_avg_entry(history, "AAPL", datetime.fromisoformat("2026-01-01T12:00:00"))
    assert entry is not None
    assert entry[0] == 100.0


def test_returns_none_without_a_preceding_buy():
    history: list[dict] = []
    entry = _reconstruct_avg_entry(history, "AAPL", datetime.fromisoformat("2026-01-01T10:00:00"))
    assert entry is None


def test_run_daily_postmortem_end_to_end_reentry(tmp_db):
    """Full run_daily_postmortem() over the exact re-entry scenario above —
    the persisted buy_price for the first SELL must be 100.0, not 200.0.
    """
    p = Portfolio()
    p.trade_history = [
        _trade("2026-01-01T09:00:00", "BUY", "AAPL", 10.0, 100.0),
        _trade("2026-01-01T10:00:00", "SELL", "AAPL", 10.0, 105.0),
        _trade("2026-01-01T11:00:00", "BUY", "AAPL", 5.0, 200.0),
        _trade("2026-01-01T12:00:00", "SELL", "AAPL", 5.0, 210.0),
    ]

    import agents.multi as multi_mod
    from unittest.mock import patch

    today_iso = datetime.now().date().isoformat()
    for t in p.trade_history:
        t["time"] = t["time"].replace("2026-01-01", today_iso)

    with patch.object(multi_mod, "_sim_mode", {"enabled": True}):
        run_daily_postmortem(p)

    import sqlite3

    with sqlite3.connect(tmp_db) as con:
        rows = con.execute(
            "SELECT buy_price, sell_price FROM postmortem ORDER BY id ASC"
        ).fetchall()

    assert len(rows) == 2
    assert rows[0] == (100.0, 105.0)
    assert rows[1] == (200.0, 210.0)


def test_today_realized_pnl_pcts_uses_reconstructed_entry():
    """The Discord daily digest's PnL list must use _reconstruct_avg_entry,
    not a naive last-BUY search — same re-entry scenario as the postmortem
    fix: sell1 must be priced against buy1 (100.0 -> +5%), not buy2 (200.0).
    """
    p = Portfolio()
    today_iso = datetime.now().date().isoformat()
    p.trade_history = [
        _trade(f"{today_iso}T09:00:00", "BUY", "AAPL", 10.0, 100.0),
        _trade(f"{today_iso}T10:00:00", "SELL", "AAPL", 10.0, 105.0),
        _trade(f"{today_iso}T11:00:00", "BUY", "AAPL", 5.0, 200.0),
        _trade(f"{today_iso}T12:00:00", "SELL", "AAPL", 5.0, 210.0),
    ]

    pnls = _today_realized_pnl_pcts(p)

    assert len(pnls) == 2
    assert pnls[0] == pytest.approx(5.0)  # (105-100)/100
    assert pnls[1] == pytest.approx(5.0)  # (210-200)/200


def test_agents_correct_scoped_to_this_trades_own_cycle(tmp_db):
    """agents_correct must reflect THIS trade's own contributing SELL
    voters (its trace_id), not any historical was_correct=1 SELL vote on
    the same symbol from an unrelated past trade — the old query filtered
    only by symbol, so an unrelated agent's stale, unrelated correct call
    could be misattributed as if it were behind today's decision (Review
    Finding).
    """
    import json
    import sqlite3
    from unittest.mock import patch

    import agents.multi as multi_mod

    today_iso = datetime.now().date().isoformat()
    old_time = f"{today_iso}T05:00:00"
    sell_time = f"{today_iso}T10:00:00"

    with sqlite3.connect(tmp_db) as con:
        # An unrelated PAST trade (different cycle) with a historically
        # correct SELL vote on the same symbol.
        con.execute(
            "INSERT INTO trades (timestamp, symbol, action, trace_id) VALUES (?,?,?,?)",
            (old_time, "AAPL", "SELL", "T-OLD"),
        )
        con.execute(
            "INSERT INTO agent_memory "
            "(timestamp, agent_name, symbol, vote, confidence, was_correct, source, trace_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (old_time, "technician", "AAPL", "SELL", 0.8, 1, "sim", "T-OLD"),
        )
        # THIS trade's own cycle: analyst voted SELL (not yet evaluated —
        # was_correct stays NULL until evaluate_pending_trades resolves it
        # days later).
        con.execute(
            "INSERT INTO trades (timestamp, symbol, action, trace_id) VALUES (?,?,?,?)",
            (sell_time, "AAPL", "SELL", "T-NEW"),
        )
        con.execute(
            "INSERT INTO agent_memory "
            "(timestamp, agent_name, symbol, vote, confidence, was_correct, source, trace_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (sell_time, "analyst", "AAPL", "SELL", 0.8, None, "sim", "T-NEW"),
        )
        con.commit()

    p = Portfolio()
    p.trade_history = [
        _trade(f"{today_iso}T09:00:00", "BUY", "AAPL", 10.0, 100.0),
        _trade(sell_time, "SELL", "AAPL", 10.0, 105.0),
    ]

    with patch.object(multi_mod, "_sim_mode", {"enabled": True}):
        run_daily_postmortem(p)

    with sqlite3.connect(tmp_db) as con:
        row = con.execute(
            "SELECT agents_correct FROM postmortem ORDER BY id DESC LIMIT 1"
        ).fetchone()

    agents_correct = json.loads(row[0])
    assert agents_correct == ["analyst"], (
        "must attribute agents_correct to THIS trade's own trace_id (analyst), "
        f"not an unrelated historical trade's technician — got {agents_correct}"
    )


def test_rolling_7d_closed_sell_pnls_uses_reconstructed_entry():
    """The weekly Discord report's per-symbol PnL must use the same
    reconstruction — a pyramided position's first SELL must be priced
    against the weighted-average entry across both BUY layers.
    """
    p = Portfolio()
    now = datetime.now()
    t0 = (now - timedelta(hours=3)).isoformat()
    t1 = (now - timedelta(hours=2)).isoformat()
    t2 = (now - timedelta(hours=1)).isoformat()
    p.trade_history = [
        _trade(t0, "BUY", "AAPL", 10.0, 100.0),  # $1000
        _trade(t1, "BUY", "AAPL", 10.0, 120.0),  # $1200, pyramid layer
        _trade(t2, "SELL", "AAPL", 20.0, 132.0),  # full close
    ]

    closed = _rolling_7d_closed_sell_pnls(p)

    assert len(closed) == 1
    symbol, pnl_pct = closed[0]
    assert symbol == "AAPL"
    # weighted-average entry = (1000+1200)/20 = 110.0 -> (132-110)/110 = +20%
    assert pnl_pct == pytest.approx(20.0)
