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
