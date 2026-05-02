"""Tests run_daily_digest business logic (DB query, P&L, positions, F&G) — Finding #10."""

import os
import sys
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agents.multi import run_daily_digest
from agents.shared.modes import _sim_mode

# Mardi 6 mai 2026 (ISO week : lundi 2026-05-04)
_FIXED_TODAY = date(2026, 5, 6)
_FIXED_DATE_STR = _FIXED_TODAY.isoformat()


@contextmanager
def _patch_multi_today(fixed: date):
    """Remplace ``date`` dans agents.multi (``date.today`` n'est pas patchable en place)."""
    with patch("agents.multi.date") as mock_date:
        mock_date.today.return_value = fixed
        yield


@pytest.fixture
def not_sim() -> None:
    """run_daily_digest retourne immédiatement si _sim_mode est actif (autouse)."""
    _sim_mode["enabled"] = False
    yield
    _sim_mode["enabled"] = True


def _digest_db_read(trade_rows: list) -> MagicMock:
    """Toutes les requêtes hors digest trades → [] (agent_memory / accuracies)."""

    def _side_effect(sql: str, params=()):
        if "substr(timestamp, 1, 10)" in sql and "FROM trades" in sql:
            return list(trade_rows)
        return []

    return MagicMock(side_effect=_side_effect)


def test_digest_pnl_correct(tmp_db, not_sim, portfolio) -> None:
    """Deux trades du jour en DB ; P&L jour = portfolio vs baseline ; trades_summary rempli."""
    portfolio.cash = 1150.0
    portfolio.positions = {}

    trade_rows = [
        ("BUY", "AAPL", 100.0, None),
        ("SELL", "AAPL", 110.0, 100.0),
    ]

    with (
        _patch_multi_today(_FIXED_TODAY),
        patch(
            "agents.shared.nodes.get_daily_start_value",
            return_value=(1000.0, _FIXED_DATE_STR),
        ),
        patch("agents.shared.nodes.get_consecutive_hold_cycles", return_value=0),
        patch("agents.multi._db_read", _digest_db_read(trade_rows)),
        patch("agents.multi.get_watchlist", return_value=[]),
        patch.object(portfolio, "fetch_prices", return_value={}),
        patch(
            "core.external_data.fetch_fear_greed",
            return_value={"score": 50, "label": "Neutral"},
        ),
        patch("core.notifications.alert_daily_digest") as ad,
    ):
        run_daily_digest(portfolio)

    kw = ad.call_args.kwargs
    assert kw["pnl_usd"] == pytest.approx(150.0)
    assert kw["pnl_pct"] == pytest.approx(15.0)
    assert len(kw["trades_summary"]) == 2
    assert kw["trades_summary"][0]["symbol"] == "AAPL"


def test_digest_no_trades(tmp_db, not_sim, portfolio) -> None:
    """Aucun trade en DB → trades_summary vide ; P&L = variation vs baseline alignée."""
    portfolio.cash = 1050.0
    portfolio.positions = {}

    with (
        _patch_multi_today(_FIXED_TODAY),
        patch(
            "agents.shared.nodes.get_daily_start_value",
            return_value=(1000.0, _FIXED_DATE_STR),
        ),
        patch("agents.shared.nodes.get_consecutive_hold_cycles", return_value=0),
        patch("agents.multi._db_read", _digest_db_read([])),
        patch("agents.multi.get_watchlist", return_value=[]),
        patch.object(portfolio, "fetch_prices", return_value={}),
        patch("core.external_data.fetch_fear_greed", return_value=None),
        patch("core.notifications.alert_daily_digest") as ad,
    ):
        run_daily_digest(portfolio)

    kw = ad.call_args.kwargs
    assert kw["trades_summary"] == []
    assert kw["pnl_usd"] == pytest.approx(50.0)
    assert kw["pnl_pct"] == pytest.approx(5.0)


def test_digest_positions_listed(tmp_db, not_sim, portfolio) -> None:
    """Deux positions ouvertes → le mapping ``positions`` passé au digest contient chaque symbole."""
    portfolio.cash = 0.0
    portfolio.positions = {
        "AAPL": {"shares": 1.0, "avg_price": 100.0},
        "MSFT": {"shares": 2.0, "avg_price": 200.0},
    }
    prices = {"AAPL": 110.0, "MSFT": 220.0}

    with (
        _patch_multi_today(_FIXED_TODAY),
        patch(
            "agents.shared.nodes.get_daily_start_value",
            return_value=(1000.0, _FIXED_DATE_STR),
        ),
        patch("agents.shared.nodes.get_consecutive_hold_cycles", return_value=0),
        patch("agents.multi._db_read", _digest_db_read([])),
        patch("agents.multi.get_watchlist", return_value=list(prices.keys())),
        patch.object(portfolio, "fetch_prices", return_value=prices),
        patch("core.external_data.fetch_fear_greed", return_value=None),
        patch("core.notifications.alert_daily_digest") as ad,
    ):
        run_daily_digest(portfolio)

    pos = ad.call_args.kwargs["positions"]
    assert set(pos.keys()) == {"AAPL", "MSFT"}
    assert pos["AAPL"]["shares"] == 1.0
    assert pos["MSFT"]["current"] == 220.0


def test_digest_fear_greed_none(tmp_db, not_sim, portfolio) -> None:
    """Score F&G indisponible → aucun champ « Fear & Greed » dans l'embed Discord."""
    portfolio.cash = 1000.0
    portfolio.positions = {}

    with (
        _patch_multi_today(_FIXED_TODAY),
        patch(
            "agents.shared.nodes.get_daily_start_value",
            return_value=(1000.0, _FIXED_DATE_STR),
        ),
        patch("agents.shared.nodes.get_consecutive_hold_cycles", return_value=0),
        patch("agents.multi._db_read", _digest_db_read([])),
        patch("agents.multi.get_watchlist", return_value=[]),
        patch.object(portfolio, "fetch_prices", return_value={}),
        patch(
            "core.external_data.fetch_fear_greed",
            return_value={"score": None, "label": "—"},
        ),
        patch("core.notifications.send_discord_alert") as sd,
    ):
        run_daily_digest(portfolio)

    fields = sd.call_args.kwargs.get("fields") or []
    names = {f.get("name") for f in fields}
    assert "Fear & Greed" not in names


def test_digest_not_sent_after_restart(tmp_db, not_sim, portfolio) -> None:
    """Baseline absente ou date ≠ jour courant (ex. après redémarrage) → P&L jour forcé à 0."""
    portfolio.cash = 2000.0
    portfolio.positions = {}

    with (
        _patch_multi_today(_FIXED_TODAY),
        patch(
            "agents.shared.nodes.get_daily_start_value",
            return_value=(1000.0, "2026-05-01"),
        ),
        patch("agents.shared.nodes.get_consecutive_hold_cycles", return_value=0),
        patch("agents.multi._db_read", _digest_db_read([])),
        patch("agents.multi.get_watchlist", return_value=[]),
        patch.object(portfolio, "fetch_prices", return_value={}),
        patch("core.external_data.fetch_fear_greed", return_value=None),
        patch("core.notifications.alert_daily_digest") as ad,
    ):
        run_daily_digest(portfolio)

    kw = ad.call_args.kwargs
    assert kw["pnl_usd"] == pytest.approx(0.0)
    assert kw["pnl_pct"] == pytest.approx(0.0)
    assert kw["portfolio_value"] == pytest.approx(2000.0)
