"""Tests for optional Discord notifications (mocked HTTP)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import core.notifications as n


def test_discord_disabled_when_no_url(monkeypatch) -> None:
    """No POST when webhook URL is empty."""

    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "")
    assert n.discord_notifications_enabled() is False
    with patch("core.notifications.httpx.post") as post:
        n.send_discord_alert("t", "d")
    post.assert_not_called()


def test_alert_trade_posts_embed(monkeypatch) -> None:
    """Trade alert sends embed with symbol in description."""
    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_trade(
            symbol="AAPL",
            action="BUY",
            price=100.0,
            amount_usd=500.0,
            votes_summary="technician: BUY AAPL (+70%)",
        )
    post.assert_called_once()
    assert post.call_args.kwargs["timeout"] == 5.0
    payload = post.call_args.kwargs["json"]
    assert "embeds" in payload
    assert "AAPL" in payload["embeds"][0]["description"]


def test_alert_trade_partial_sell_includes_sell_pct(monkeypatch) -> None:
    """Partial SELL trade mentions sell_pct in description."""
    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_trade(
            symbol="MSFT",
            action="SELL",
            price=50.0,
            sell_pct=50.0,
            amount_usd=200.0,
        )
    desc = post.call_args.kwargs["json"]["embeds"][0]["description"]
    assert "50%" in desc


def test_fail_silent_on_http_error(monkeypatch) -> None:
    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post", side_effect=RuntimeError("network")):
        n.send_discord_alert("x", "y")


def test_posts_use_five_second_timeout(monkeypatch) -> None:
    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_startup()
    assert post.call_args.kwargs["timeout"] == 5.0


def test_daily_digest_fields(monkeypatch) -> None:
    """Daily digest embed exposes P&L, Trades, Portfolio, and Mode."""

    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_daily_digest(
            date="2026-05-02",
            pnl_usd=10.0,
            pnl_pct=1.0,
            portfolio_value=1010.0,
            trades_summary=[
                {"action": "BUY", "symbol": "AAPL", "price": 180.0, "sell_pct": None},
            ],
            positions={},
            agent_accuracy={
                "technician": None,
                "analyst": None,
                "risk_manager": None,
                "macro_watcher": None,
            },
            consecutive_holds=0,
            mode="LIVE",
            realized_pnl_pcts=None,
        )
    emb = post.call_args.kwargs["json"]["embeds"][0]
    names = {f["name"] for f in emb["fields"]}
    assert "P&L" in names
    assert "Trades" in names
    assert "Portfolio" in names
    assert "Mode" in names


def test_daily_digest_color_green(monkeypatch) -> None:
    """Positive P&L uses green embed color."""

    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_daily_digest(
            date="2026-05-02",
            pnl_usd=1.0,
            pnl_pct=0.1,
            portfolio_value=1001.0,
            trades_summary=[],
            positions={},
            agent_accuracy={
                "technician": None,
                "analyst": None,
                "risk_manager": None,
                "macro_watcher": None,
            },
            consecutive_holds=0,
            mode="LIVE",
        )
    assert post.call_args.kwargs["json"]["embeds"][0]["color"] == n._COLOR_GREEN


def test_daily_digest_color_red(monkeypatch) -> None:
    """Negative P&L uses red embed color."""

    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_daily_digest(
            date="2026-05-02",
            pnl_usd=-5.0,
            pnl_pct=-0.5,
            portfolio_value=995.0,
            trades_summary=[],
            positions={},
            agent_accuracy={
                "technician": None,
                "analyst": None,
                "risk_manager": None,
                "macro_watcher": None,
            },
            consecutive_holds=0,
            mode="LIVE",
        )
    assert post.call_args.kwargs["json"]["embeds"][0]["color"] == n._COLOR_RED


def test_daily_digest_not_sent_in_sim(monkeypatch) -> None:
    """``run_daily_digest`` does not POST when simulation mode is on."""

    from agents.multi import run_daily_digest
    from agents.shared.modes import _sim_mode

    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    _sim_mode["enabled"] = True
    try:
        with patch("core.notifications.httpx.post") as post:
            run_daily_digest(MagicMock())
        post.assert_not_called()
    finally:
        _sim_mode["enabled"] = False


def test_weekly_report_fields(monkeypatch) -> None:
    """Weekly embed includes win rate, vs SPY, and agent ranking."""

    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_weekly_report(
            week_start="2026-04-28",
            week_end="2026-05-04",
            pnl_usd=50.0,
            pnl_pct=5.0,
            portfolio_value=1050.0,
            total_trades=10,
            win_rate=0.5,
            best_trade={"symbol": "X", "pnl_pct": 1.0},
            worst_trade={"symbol": "Y", "pnl_pct": -1.0},
            agent_ranking=[{"name": "technician", "accuracy": 0.7, "trades": 3}],
            spy_pct=2.0,
            mode="LIVE",
            win_count=1,
            closed_trades=2,
        )
    emb = post.call_args.kwargs["json"]["embeds"][0]
    names = {f["name"] for f in emb["fields"]}
    assert "Win rate" in names
    assert "vs SPY" in names
    assert "Agent ranking" in names


def test_weekly_report_only_on_sunday(monkeypatch) -> None:
    """Non-Sunday scheduled run must not invoke ``run_weekly_report``."""

    import dashboard.controller as ctrl
    from config import POSTMORTEM_HOUR

    port = MagicMock()
    now = MagicMock(spec=datetime)
    now.date.return_value = date(2026, 5, 5)
    now.hour = POSTMORTEM_HOUR
    now.weekday.return_value = 1

    ctrl._last_postmortem_date = None
    try:
        with patch.object(ctrl, "run_daily_postmortem"):
            with patch.object(ctrl, "run_daily_digest"):
                with patch.object(ctrl, "run_weekly_report") as rw:
                    ctrl._run_digest_and_weekly_at_postmortem_hour(port, now)
        rw.assert_not_called()
    finally:
        ctrl._last_postmortem_date = None


def test_evaluation_alert_correct(monkeypatch) -> None:
    """was_correct=True → green embed and CORRECT in title."""

    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_evaluation(
            symbol="AAPL",
            action="BUY",
            entry_price=100.0,
            current_price=102.0,
            pct_change=0.02,
            was_correct=True,
            days_held=7,
            mode="LIVE",
        )
    emb = post.call_args.kwargs["json"]["embeds"][0]
    assert "CORRECT" in emb["title"]
    assert emb["color"] == n.COLOR_CORRECT


def test_evaluation_alert_incorrect(monkeypatch) -> None:
    """was_correct=False → red embed."""

    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_evaluation(
            symbol="MSFT",
            action="BUY",
            entry_price=200.0,
            current_price=190.0,
            pct_change=-0.05,
            was_correct=False,
            days_held=3,
            mode="PAPER",
        )
    emb = post.call_args.kwargs["json"]["embeds"][0]
    assert "INCORRECT" in emb["title"]
    assert emb["color"] == n.COLOR_INCORRECT


def test_evaluation_alert_inconclusive(monkeypatch) -> None:
    """was_correct=None → grey inconclusive embed."""

    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_evaluation(
            symbol="GOOG",
            action="SELL",
            entry_price=150.0,
            current_price=150.5,
            pct_change=150.5 / 150.0 - 1.0,
            was_correct=None,
            days_held=7,
            mode="LIVE",
        )
    emb = post.call_args.kwargs["json"]["embeds"][0]
    assert "INCONCLUSIVE" in emb["title"]
    assert emb["color"] == n.COLOR_INCONCLUSIVE
