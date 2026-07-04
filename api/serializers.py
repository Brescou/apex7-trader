"""APEX-7 — Serialize Portfolio + controller state to JSON-safe dicts."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from config import DEATH_THRESHOLD, INITIAL_BALANCE


def _sanitize(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with ``None``.

    JSON has no literal for NaN/Infinity. A single bad yfinance price
    reaching here (e.g. via ``last_prices``) would otherwise either raise
    inside a strict JSON encoder (Starlette's default JSONResponse uses
    ``allow_nan=False``) — a 500 on ``/api/portfolio`` — or, with a
    permissive encoder, emit the literal tokens ``NaN``/``Infinity``, which
    is not valid JSON and makes every WebSocket client's ``JSON.parse``
    throw on that snapshot.
    """
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _fmt(n: float, decimals: int = 2) -> str:
    return f"{n:,.{decimals}f}"


def _pct(n: float) -> str:
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.2f}%"


def serialize_state(
    portfolio,
    cycle: int,
    thinking: bool,
    mode: str,
    votes: list,
    arb: dict,
    consecutive_holds: int,
) -> dict[str, Any]:
    with portfolio._lock:
        cash = portfolio.cash
        # dict(portfolio.positions) only copies the OUTER dict — each inner
        # position dict would still be the same live object the agent
        # thread mutates in place (e.g. Portfolio.buy()'s pyramid branch
        # updates avg_price/shares/layers as separate writes). Reading those
        # fields below happens AFTER releasing the lock, so a shallow copy
        # risked a torn read (new shares, stale avg_price). Copy each
        # position dict too while still holding the lock (Review Finding).
        positions = {sym: dict(pos) for sym, pos in portfolio.positions.items()}
        value_history = list(portfolio.value_history[-200:])
        agent_log = list(portfolio.agent_log[-100:])
        peak_value = portfolio.peak_value
        is_dead = portfolio.is_dead
        last_prices = dict(portfolio.last_prices)

    total = cash + sum(
        pos["shares"] * last_prices.get(sym, pos.get("avg_price", 0))
        for sym, pos in positions.items()
    )
    pnl = total - INITIAL_BALANCE
    pnl_pct = pnl / INITIAL_BALANCE * 100
    survival_pct = min(98, max(4, (total - DEATH_THRESHOLD) / (2000 - DEATH_THRESHOLD) * 100))

    # Positions
    positions_out = []
    for sym, pos in positions.items():
        last = last_prices.get(sym, pos.get("avg_price", 0))
        avg = pos.get("avg_price", pos.get("avg_cost", 0))
        pos_value = pos["shares"] * last
        pnl_pos = (last - avg) / avg * 100 if avg else 0
        alloc_pct = pos_value / total * 100 if total else 0
        positions_out.append(
            {
                "sym": sym,
                "shares": round(pos["shares"], 4),
                "avgPrice": round(avg, 2),
                "lastPrice": round(last, 2),
                "value": round(pos_value, 2),
                "pnlPct": round(pnl_pos, 2),
                "allocPct": round(alloc_pct, 1),
                "layers": pos.get("layers", 1),
                "openedAt": pos.get("opened_at", ""),
            }
        )

    # Equity series (value_history → [{time, value}])
    equity = [{"t": e["time"][:19], "v": round(e["value"], 2)} for e in value_history]

    # Agent votes
    votes_out = []
    for v in votes:
        if isinstance(v, dict):
            votes_out.append(v)
        elif hasattr(v, "model_dump"):
            votes_out.append(v.model_dump())
        elif hasattr(v, "__dict__"):
            votes_out.append(vars(v))

    # Activity log (newest first, last 80)
    log_out = [
        {"t": e["time"][11:19], "msg": e["message"], "level": e.get("level", "info")}
        for e in reversed(agent_log[-80:])
    ]

    # Emotion
    emotion = _derive_emotion(total)

    return _sanitize(
        {
            # Portfolio
            "value": round(total, 2),
            "valueStr": _fmt(total),
            "cash": round(cash, 2),
            "cashStr": _fmt(cash),
            "pnl": round(pnl, 2),
            "pnlStr": ("+" if pnl >= 0 else "") + _fmt(abs(pnl)),
            "pnlPct": round(pnl_pct, 2),
            "pnlPctStr": _pct(pnl_pct),
            "peakValue": round(peak_value, 2),
            "survivalPct": round(survival_pct, 1),
            "deathThreshold": DEATH_THRESHOLD,
            "initialBalance": INITIAL_BALANCE,
            "isDead": is_dead,
            "positions": positions_out,
            # Agent
            "cycle": cycle,
            "thinking": thinking,
            "mode": mode,
            "consecutiveHolds": consecutive_holds,
            "votes": votes_out,
            "arbitration": arb if isinstance(arb, dict) else {},
            "emotion": emotion,
            # Chart
            "equity": equity,
            # Log
            "log": log_out,
            # Meta
            "timestamp": datetime.now().isoformat(),
        }
    )


def _derive_emotion(value: float) -> dict:
    if value >= 1400:
        return {
            "state": "CONFIDENT",
            "color": "#2dd4a0",
            "quote": "Edge is real. Press it, don't squander it.",
        }
    if value >= 1100:
        return {
            "state": "FOCUSED",
            "color": "#3fc7c0",
            "quote": "Steady gains. Stay disciplined, no heroics.",
        }
    if value >= 700:
        return {
            "state": "CAUTIOUS",
            "color": "#e3b341",
            "quote": "Buffer thinning. Protect capital first.",
        }
    if value >= 200:
        return {
            "state": "ANXIOUS",
            "color": "#f0934d",
            "quote": "Runway short. Every trade must earn its place.",
        }
    return {
        "state": "DESPERATE",
        "color": "#f2596b",
        "quote": "Death is close. One wrong move ends it.",
    }
