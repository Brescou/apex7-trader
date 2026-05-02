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
    fields = [{"name": "Mode", "value": _runtime_mode_label(), "inline": True}]
    send_discord_alert("APEX-7 death", desc, color=_COLOR_RED, fields=fields)


def alert_stagnation(*, hold_cycles: int) -> None:
    """Too many consecutive HOLD cycles (rule-based stagnation hook)."""
    send_discord_alert(
        "APEX-7 stagnation",
        f"Hold streak reached **{hold_cycles}** cycles without action.",
        color=_COLOR_ORANGE,
        fields=[{"name": "Mode", "value": _runtime_mode_label(), "inline": True}],
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
    """Trailing stop-loss triggered (Feature 3 — wired from ``execute_node``)."""
    send_discord_alert(
        "APEX-7 trailing stop",
        f"`{symbol}` @ `{price:.4f}` — high `{high_watermark:.4f}`, "
        f"drawdown from high `{drawdown_pct * 100:.2f}%`",
        color=_COLOR_ORANGE,
        fields=[{"name": "Mode", "value": _runtime_mode_label(), "inline": True}],
    )


_AGENT_DIGEST_SHORT = {
    "technician": "TECH",
    "analyst": "ANLST",
    "risk_manager": "RISK",
    "macro_watcher": "MACRO",
}


def _format_digest_trades_line(trades_summary: list[dict]) -> str:
    """Build a compact BUY / SELL summary for the digest embed."""
    n_buy = sum(1 for t in trades_summary if (t.get("action") or "").upper() == "BUY")
    sells = [t for t in trades_summary if (t.get("action") or "").upper() == "SELL"]
    parts: list[str] = []
    if n_buy:
        parts.append(f"{n_buy} BUY")
    full_sells = 0
    partial_labels: list[str] = []
    for t in sells:
        sp = t.get("sell_pct")
        if sp is not None and float(sp) < 100.0:
            partial_labels.append(f"SELL {float(sp):.0f}%")
        else:
            full_sells += 1
    if full_sells:
        parts.append(f"{full_sells} SELL")
    parts.extend(partial_labels)
    return " · ".join(parts) if parts else "None"


def _format_digest_positions(positions: dict[str, dict]) -> str:
    """Multi-line open positions + unrealized P&L (truncated for Discord)."""
    if not positions:
        return "None"
    lines: list[str] = []
    for sym, pos in sorted(positions.items()):
        cur = float(pos.get("current", 0))
        avg = float(pos.get("avg_price", 0))
        pnl = float(pos.get("pnl_pct", 0))
        sh = float(pos.get("shares", 0))
        lines.append(f"`{sym}` {sh:.4f} sh @ ${avg:.2f} → ${cur:.2f} (**{pnl:+.1f}%**)")
    text = "\n".join(lines)
    return text[:1000] + ("…" if len(text) > 1000 else "")


def _format_digest_agent_accuracy(agent_accuracy: dict[str, float | None]) -> str:
    chips: list[str] = []
    for key, short in _AGENT_DIGEST_SHORT.items():
        acc = agent_accuracy.get(key)
        if acc is None:
            chips.append(f"⏳ {short}")
        else:
            chips.append(f"{short} {acc:.0%}")
    return " · ".join(chips)


def alert_daily_digest(
    *,
    date: str,
    pnl_usd: float,
    pnl_pct: float,
    portfolio_value: float,
    trades_summary: list[dict],
    positions: dict[str, dict],
    agent_accuracy: dict[str, float | None],
    consecutive_holds: int,
    mode: str,
    realized_pnl_pcts: list[float] | None = None,
) -> None:
    """End-of-day summary embed at ``POSTMORTEM_HOUR`` (live / paper only).

    ``realized_pnl_pcts`` holds percent P&L for each same-day SELL vs its entry
    (computed in ``run_daily_digest``); used for Best / Worst field.
    """
    if pnl_usd >= 0:
        pnl_field = f"+${pnl_usd:,.2f} (+{pnl_pct:.1f}%)"
    else:
        pnl_field = f"-${-pnl_usd:,.2f} ({pnl_pct:.1f}%)"
    color = _COLOR_GREEN if pnl_usd >= 0 else _COLOR_RED

    fields: list[dict[str, Any]] = [
        {"name": "P&L", "value": pnl_field, "inline": True},
        {
            "name": "Portfolio",
            "value": f"${portfolio_value:,.2f}",
            "inline": True,
        },
        {
            "name": "Trades",
            "value": _format_digest_trades_line(trades_summary),
            "inline": False,
        },
        {
            "name": "Positions",
            "value": _format_digest_positions(positions),
            "inline": False,
        },
    ]

    rp = realized_pnl_pcts or []
    if rp:
        best = max(rp)
        worst = min(rp)
        bw = f"Best **{best:+.2f}%** · Worst **{worst:+.2f}%**"
    else:
        bw = "— (no closed trades today)"
    fields.append({"name": "Best / Worst", "value": bw, "inline": False})

    fields.append(
        {
            "name": "Agent accuracy",
            "value": _format_digest_agent_accuracy(agent_accuracy),
            "inline": False,
        }
    )
    if consecutive_holds > 0:
        fields.append(
            {
                "name": "Holds",
                "value": f"{consecutive_holds} consecutive",
                "inline": True,
            }
        )
    fields.append({"name": "Mode", "value": mode[:256], "inline": True})

    title = f"📊 APEX-7 Daily Digest — {date}"
    send_discord_alert(
        title,
        "",
        color=color,
        fields=fields,
    )
