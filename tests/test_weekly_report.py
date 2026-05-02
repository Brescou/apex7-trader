"""Tests for weekly Discord report: sim skip + business logic (Finding #10)."""

import os
import sys
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agents.multi import run_weekly_report
from agents.shared.modes import _sim_mode

_FIXED_TODAY = date(2026, 5, 6)
_WEEK_START = date(2026, 5, 4).isoformat()


@contextmanager
def _patch_multi_today(fixed: date):
    """Mock ``date.today()`` dans ``agents.multi`` (le type ``date`` est immuable)."""
    with patch("agents.multi.date") as mock_date:
        mock_date.today.return_value = fixed
        yield


@pytest.fixture
def not_sim() -> None:
    """Évite le early-return de run_weekly_report (autouse active le sim)."""
    _sim_mode["enabled"] = False
    yield
    _sim_mode["enabled"] = True


def test_run_weekly_report_skips_in_simulation_mode() -> None:
    """No Discord call when simulation mode is enabled."""
    _sim_mode["enabled"] = True
    try:
        with patch("core.notifications.alert_weekly_report") as aw:
            run_weekly_report(MagicMock())
        aw.assert_not_called()
    finally:
        _sim_mode["enabled"] = False


def test_weekly_spy_none(tmp_db, not_sim, portfolio) -> None:
    """Échec / données SPY insuffisantes → spy_pct None ; libellé « unavailable » côté notification."""
    portfolio.cash = 1000.0
    portfolio.positions = {}

    with (
        _patch_multi_today(_FIXED_TODAY),
        patch(
            "agents.multi.get_weekly_start_value",
            return_value=(950.0, _WEEK_START),
        ),
        patch("agents.multi.yf.download", return_value=None),
        patch("agents.multi.get_watchlist", return_value=[]),
        patch.object(portfolio, "fetch_prices", return_value={}),
        patch("core.notifications.alert_weekly_report") as aw,
    ):
        run_weekly_report(portfolio)

    assert aw.call_args.kwargs["spy_pct"] is None

    with patch("core.notifications.send_discord_alert") as sd:
        from core.notifications import alert_weekly_report

        alert_weekly_report(
            week_start=_WEEK_START,
            week_end=_FIXED_TODAY.isoformat(),
            pnl_usd=50.0,
            pnl_pct=5.0,
            portfolio_value=1000.0,
            total_trades=0,
            win_rate=0.0,
            best_trade=None,
            worst_trade=None,
            agent_ranking=[],
            spy_pct=None,
            mode="LIVE",
            win_count=0,
            closed_trades=0,
        )
    fields = sd.call_args.kwargs["fields"]
    vs = next(f for f in fields if f["name"] == "vs SPY")
    assert "unavailable" in vs["value"].lower()


def test_weekly_no_closed_trades(tmp_db, not_sim, portfolio) -> None:
    """Aucune vente réalisée sur 7 jours → win_rate 0, best / worst None."""
    portfolio.cash = 1000.0
    portfolio.positions = {}
    portfolio.trade_history = []

    with (
        _patch_multi_today(_FIXED_TODAY),
        patch(
            "agents.multi.get_weekly_start_value",
            return_value=(1000.0, _WEEK_START),
        ),
        patch("agents.multi.yf.download", return_value=None),
        patch("agents.multi.get_watchlist", return_value=[]),
        patch.object(portfolio, "fetch_prices", return_value={}),
        patch("core.notifications.alert_weekly_report") as aw,
    ):
        run_weekly_report(portfolio)

    kw = aw.call_args.kwargs
    assert kw["win_rate"] == pytest.approx(0.0)
    assert kw["closed_trades"] == 0
    assert kw["best_trade"] is None
    assert kw["worst_trade"] is None


def test_weekly_agent_ranking_empty(tmp_db, not_sim, portfolio) -> None:
    """Aucun vote agent évalué en base → rang avec accuracy None et marqueur ⏳ (warm-up)."""
    portfolio.cash = 1000.0
    portfolio.positions = {}

    with (
        _patch_multi_today(_FIXED_TODAY),
        patch(
            "agents.multi.get_weekly_start_value",
            return_value=(1000.0, _WEEK_START),
        ),
        patch("agents.multi.yf.download", return_value=None),
        patch("agents.multi.get_watchlist", return_value=[]),
        patch.object(portfolio, "fetch_prices", return_value={}),
        patch("core.notifications.alert_weekly_report") as aw,
    ):
        run_weekly_report(portfolio)

    ranking = aw.call_args.kwargs["agent_ranking"]
    assert ranking
    assert all(row.get("accuracy") is None for row in ranking)

    from core.notifications import _format_weekly_agent_ranking

    text = _format_weekly_agent_ranking(ranking)
    assert "⏳" in text
