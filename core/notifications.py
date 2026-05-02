"""Optional Discord webhook alerts — fire-and-forget, fail-silent."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger("apex7.notify")

_COLOR_BLUE = 0x5865F2
_COLOR_GREEN = 0x57F287
_COLOR_RED = 0xED4245
_COLOR_ORANGE = 0xFEE75C
_COLOR_GOLD = 0xF0B232


def _webhook_url() -> str:
    """Return trimmed webhook URL from config (empty when unset)."""
    from config import DISCORD_WEBHOOK_URL

    return DISCORD_WEBHOOK_URL or ""


def discord_notifications_enabled() -> bool:
    """True when a Discord webhook URL is configured."""
    return bool(_webhook_url())


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post_payload(payload: dict[str, Any]) -> None:
    url = _webhook_url()
    if not url:
        return
    try:
        httpx.post(url, json=payload, timeout=5.0)
    except Exception as exc:
        logger.debug("Discord webhook failed: %s", exc)


def send_discord_alert(
    title: str,
    description: str,
    *,
    color: int = _COLOR_BLUE,
    fields: list[dict[str, Any]] | None = None,
) -> None:
    """Send a single embed. No-op when webhook is unset; errors are swallowed."""
    embed: dict[str, Any] = {
        "title": title[:256],
        "description": (description or "")[:4096],
        "color": color,
        "timestamp": _utc_iso(),
    }
    if fields:
        embed["fields"] = fields[:25]
    _post_payload({"embeds": [embed]})


def _runtime_mode_label() -> str:
    try:
        from agents.shared.nodes import get_runtime_mode

        return str(get_runtime_mode() or "live")
    except Exception:
        return "unknown"


def alert_trade(
    *,
    symbol: str,
    action: str,
    price: float | None = None,
    amount_usd: float | None = None,
    sell_pct: float | None = None,
    confidence: float | None = None,
    votes_summary: str | None = None,
) -> None:
    """Notify an executed BUY/SELL (after DB persistence)."""
    lines = [
        f"**{action}** `{symbol}`",
    ]
    if price is not None:
        lines.append(f"Price: `{price:.4f}`")
    if amount_usd is not None:
        lines.append(f"Notional: `${amount_usd:,.2f}`")
    if sell_pct is not None and action.upper() == "SELL":
        lines.append(f"Sell %: `{sell_pct:g}%`")
    if confidence is not None:
        lines.append(f"Confidence: `{confidence:.0%}`")
    body = "\n".join(lines)
    fields: list[dict[str, Any]] = [
        {"name": "Mode", "value": _runtime_mode_label(), "inline": True}
    ]
    if votes_summary:
        fields.append({"name": "Votes", "value": votes_summary[:1024], "inline": False})
    send_discord_alert(
        "APEX-7 trade",
        body,
        color=_COLOR_GREEN if action.upper() == "BUY" else _COLOR_BLUE,
        fields=fields,
    )


def alert_death(*, portfolio_value: float | None = None) -> None:
    """Portfolio crossed death threshold."""
    desc = "Portfolio is dead (below survival threshold)."
    if portfolio_value is not None:
        desc += f"\nLast value: `${portfolio_value:,.2f}`"
    send_discord_alert("APEX-7 death", desc, color=_COLOR_RED)


def alert_stagnation(*, hold_cycles: int) -> None:
    """Too many consecutive HOLD cycles (rule-based stagnation hook)."""
    send_discord_alert(
        "APEX-7 stagnation",
        f"Hold streak reached **{hold_cycles}** cycles without action.",
        color=_COLOR_ORANGE,
    )


def alert_circuit_breaker(reason: str, wait_seconds: int) -> None:
    """LLM circuit breaker or rate limit backoff."""
    send_discord_alert(
        "APEX-7 circuit breaker",
        f"{reason}\nRetry/backoff: **{wait_seconds}s**",
        color=_COLOR_GOLD,
    )


def alert_startup() -> None:
    """Dashboard / controller started."""
    send_discord_alert(
        "APEX-7 startup",
        "Controller started.",
        color=_COLOR_GREEN,
        fields=[{"name": "Mode", "value": _runtime_mode_label(), "inline": True}],
    )


def alert_trailing_stop(
    *,
    symbol: str,
    price: float,
    high_watermark: float,
    drawdown_pct: float,
) -> None:
    """Trailing stop-loss triggered (Feature 4 — wired from ``execute_node``)."""
    send_discord_alert(
        "APEX-7 trailing stop",
        f"`{symbol}` @ `{price:.4f}` — high `{high_watermark:.4f}`, "
        f"drawdown from high `{drawdown_pct * 100:.2f}%`",
        color=_COLOR_ORANGE,
        fields=[{"name": "Mode", "value": _runtime_mode_label(), "inline": True}],
    )
