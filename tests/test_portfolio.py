"""Unit tests for ``Portfolio`` sell validation."""

import math
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import config
from core.data import Portfolio


def _p_with_aapl() -> Portfolio:
    p = Portfolio()
    with p._lock:
        p.positions["AAPL"] = {"shares": 1.0, "avg_price": 100.0}
        p.cash = 500.0
    return p


def test_sell_rejects_zero_price() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 100, 0.0)
    assert r["success"] is False
    assert "AAPL" in p.positions


def test_sell_rejects_negative_price() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 100, -5.0)
    assert r["success"] is False


def test_sell_rejects_nan_price() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 100, float("nan"))
    assert r["success"] is False


def test_sell_normal_price() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 100, 150.0)
    assert r["success"] is True
    assert "AAPL" not in p.positions
    assert not math.isnan(p.cash)


def test_sell_rejects_zero_pct() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 0, 150.0)
    assert r["success"] is False
    assert "AAPL" in p.positions


def test_sell_rejects_pct_over_100() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 100.5, 150.0)
    assert r["success"] is False
    assert "AAPL" in p.positions


def test_buy_not_recapped_by_alloc_pct_of_cash_alone() -> None:
    """Sizing (MAX_ALLOC_PCT of *portfolio value*) is execute_node's job.

    Portfolio.buy() must only reject/shrink a BUY for affordability (enough
    cash to cover amount + commission) — it must not silently re-shrink an
    already-correctly-sized amount using MAX_ALLOC_PCT of *cash* alone. A
    portfolio holding a big existing position (cash a minority of total
    value) legitimately requests an amount well above 40% of its remaining
    cash but still affordable; that must go through in full, not get capped
    to ~40% of cash (Review Finding).
    """
    from config import MAX_ALLOC_PCT

    p = Portfolio()
    with p._lock:
        p.positions["MSFT"] = {"shares": 10.0, "avg_price": 100.0}
        p.cash = 200.0  # total portfolio value ~= 200 + 1000 = 1200

    requested = 150.0  # > 40% of the 200 cash, but easily affordable
    assert requested > p.cash * (MAX_ALLOC_PCT / 100)

    r = p.buy("AAPL", requested, 100.0)
    assert r["success"] is True
    assert r["amount"] == pytest.approx(requested, abs=0.01)


_N_TICKS = 750  # comfortably above any reasonable in-memory cap


def test_value_history_capped_in_memory() -> None:
    """record_value() must bound value_history in memory as it runs — only
    save_state() truncated it before, so a long-running agent process (live
    ticks every 30s, forever) grew this list without bound between restarts
    (Review Finding). Without a cap, ``_N_TICKS`` appends (starting from the
    1 seed entry in ``__init__``) leave the list at ``_N_TICKS + 1`` entries.
    """
    p = Portfolio()
    for _ in range(_N_TICKS):
        p.record_value({})
    assert len(p.value_history) < _N_TICKS
    # Most recent entry must survive the trim (not an arbitrary prefix kept).
    assert p.value_history[-1]["value"] == pytest.approx(p.cash)


def test_agent_log_capped_in_memory() -> None:
    """log() must bound agent_log in memory — it is never persisted by
    save_state() at all, so without an in-memory cap it grows for the
    entire lifetime of the process (Review Finding). Without a cap,
    ``_N_TICKS`` calls leave the list at exactly ``_N_TICKS`` entries.
    """
    p = Portfolio()
    for i in range(_N_TICKS):
        p.log(f"tick {i}")
    assert len(p.agent_log) < _N_TICKS
    assert p.agent_log[-1]["message"] == f"tick {_N_TICKS - 1}"


def test_fetch_prices_respects_use_livefeed_toggle_at_runtime(monkeypatch) -> None:
    """USE_LIVEFEED must be read live via config.USE_LIVEFEED, not frozen at
    import time. ``from config import USE_LIVEFEED`` binds a separate,
    frozen copy in core.data's namespace — monkeypatching
    config.USE_LIVEFEED (the only way to toggle it after config.py has
    already been imported; the env var itself is only read once, at
    import) would then silently have no effect on Portfolio.fetch_prices()
    (Review Finding — same bug class already fixed for
    agents/shared/eval.py's _get_db_path).

    The test suite runs with USE_LIVEFEED=false on the command line, so
    core.data's import-time-frozen copy (if the bug were present) would
    already read False regardless of this test — toggle to True instead,
    so only a LIVE read of config.USE_LIVEFEED can make LiveFeed fire.
    """
    monkeypatch.setattr(config, "USE_LIVEFEED", True)

    p = Portfolio()
    with (
        patch("core.data.LiveFeed") as mock_livefeed_cls,
        patch("core.data.yf.Tickers") as mock_tickers,
    ):
        mock_livefeed_cls.return_value.fetch.return_value = {}
        mock_tickers.return_value.tickers = {}
        p.fetch_prices(["AAPL"])

    mock_livefeed_cls.assert_called_once()


def test_buy_commission_arithmetic() -> None:
    """Commission must be exactly amount_usd * COMMISSION_PCT, and cash must
    be debited by amount + commission (not amount alone) — a coverage gap
    this suite never pinned down with an exact expected value (Review
    Finding).
    """
    from config import COMMISSION_PCT, SLIPPAGE_PCT

    p = Portfolio()
    cash_before = p.cash
    r = p.buy("AAPL", 200.0, 100.0)

    assert r["success"] is True
    expected_commission = 200.0 * COMMISSION_PCT
    assert r["commission"] == pytest.approx(round(expected_commission, 4))
    assert p.cash == pytest.approx(cash_before - 200.0 - expected_commission)

    effective_px = 100.0 * (1 + SLIPPAGE_PCT)
    assert p.positions["AAPL"]["shares"] == pytest.approx(200.0 / effective_px)


def test_sell_commission_arithmetic() -> None:
    """Commission must be exactly amount * COMMISSION_PCT, and cash must be
    credited by amount - commission (not the gross amount) — a coverage
    gap this suite never pinned down with an exact expected value (Review
    Finding).
    """
    from config import COMMISSION_PCT, SLIPPAGE_PCT

    p = Portfolio()
    p.positions["AAPL"] = {"shares": 2.0, "avg_price": 100.0, "layers": 1}
    cash_before = p.cash

    r = p.sell("AAPL", 100.0, 110.0)

    assert r["success"] is True
    effective_px = 110.0 * (1 - SLIPPAGE_PCT)
    expected_amount = 2.0 * effective_px
    expected_commission = expected_amount * COMMISSION_PCT
    assert r["amount"] == pytest.approx(round(expected_amount, 2))
    assert r["commission"] == pytest.approx(round(expected_commission, 4))
    assert p.cash == pytest.approx(cash_before + expected_amount - expected_commission)
