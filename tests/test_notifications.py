"""Tests for optional Discord notifications (mocked HTTP)."""

from unittest.mock import patch

import core.notifications as n


def test_discord_disabled_when_no_url(monkeypatch) -> None:
    """No POST when webhook URL is empty."""
    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "")
    assert n.discord_notifications_enabled() is False
    with patch("core.notifications.httpx.post") as post:
        n.send_discord_alert("t", "d")
    post.assert_not_called()


def test_alert_trade_posts_embed(monkeypatch) -> None:
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


def test_alert_daily_digest_embed(monkeypatch) -> None:
    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_daily_digest(
            date="2026-05-02",
            pnl_usd=42.3,
            pnl_pct=4.2,
            portfolio_value=1042.30,
            trades_summary=[
                {"action": "BUY", "symbol": "AAPL", "price": 180.0, "sell_pct": None},
                {"action": "SELL", "symbol": "MSFT", "price": 410.0, "sell_pct": 50.0},
            ],
            positions={
                "AAPL": {
                    "shares": 1.0,
                    "avg_price": 180.0,
                    "current": 185.0,
                    "pnl_pct": 2.78,
                }
            },
            agent_accuracy={
                "technician": 0.78,
                "analyst": 0.65,
                "risk_manager": None,
                "macro_watcher": None,
            },
            consecutive_holds=3,
            mode="LIVE",
            realized_pnl_pcts=[2.5, -1.2],
        )
    post.assert_called_once()
    payload = post.call_args.kwargs["json"]
    emb = payload["embeds"][0]
    assert "Daily Digest" in emb["title"]
    assert emb["color"] == n._COLOR_GREEN
    names = {f["name"] for f in emb["fields"]}
    assert "P&L" in names
    assert "Portfolio" in names
    assert "Trades" in names
    assert "Positions" in names
    assert "Best / Worst" in names
    assert "Agent accuracy" in names
    assert "Holds" in names
    assert "Mode" in names


def test_alert_weekly_report_embed(monkeypatch) -> None:
    """Weekly embed includes P&L, win rate, SPY comparison, and ranking fields."""
    monkeypatch.setattr("config.DISCORD_WEBHOOK_URL", "https://example.com/hook")
    with patch("core.notifications.httpx.post") as post:
        n.alert_weekly_report(
            week_start="2026-04-28",
            week_end="2026-05-04",
            pnl_usd=120.0,
            pnl_pct=12.0,
            portfolio_value=1120.0,
            total_trades=24,
            win_rate=2 / 3,
            best_trade={"symbol": "AAPL", "pnl_pct": 5.2},
            worst_trade={"symbol": "TSLA", "pnl_pct": -1.1},
            agent_ranking=[
                {"name": "technician", "accuracy": 0.78, "trades": 12},
                {"name": "analyst", "accuracy": None, "trades": 4},
            ],
            spy_pct=1.8,
            mode="PAPER",
            win_count=8,
            closed_trades=12,
        )
    post.assert_called_once()
    emb = post.call_args.kwargs["json"]["embeds"][0]
    assert "Weekly Report" in emb["title"]
    assert emb["color"] == n._COLOR_GREEN
    names = {f["name"] for f in emb["fields"]}
    assert "P&L (week)" in names
    assert "Win rate" in names
    assert "vs SPY" in names
    assert (
        "outperformed" in next(f["value"] for f in emb["fields"] if f["name"] == "vs SPY").lower()
    )
