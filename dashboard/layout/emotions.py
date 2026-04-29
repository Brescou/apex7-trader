"""APEX-7 — Emotion system for agent state display."""

from core.data import Portfolio
from dashboard.controller import _controller_lock, _state
from dashboard.server import (
    BLUE,
    GRAY,
    GREEN,
    INITIAL_BALANCE,
    RED,
    YELLOW,
)

_EMOTIONS: dict[str, dict] = {
    "EUPHORIC": {"icon": "🚀", "color": GREEN, "quote": "To the moon. Nothing can stop us now."},
    "EXCITED": {"icon": "🔥", "color": GREEN, "quote": "Momentum building. Stay aggressive."},
    "FOCUSED": {"icon": "🎯", "color": BLUE, "quote": "Executing the plan. Steady hands."},
    "CALM": {"icon": "😐", "color": GRAY, "quote": "Patience. The market reveals itself."},
    "NERVOUS": {"icon": "😰", "color": YELLOW, "quote": "Risk elevated. Reduce exposure now."},
    "PANIC": {"icon": "🚨", "color": RED, "quote": "Capital preservation. Cut losses NOW."},
    "DESPERATE": {"icon": "💀", "color": RED, "quote": "One trade left. Make it count."},
}


def _emotion(total: float) -> str:
    r = total / INITIAL_BALANCE
    if r >= 1.5:
        return "EUPHORIC"
    if r >= 1.2:
        return "EXCITED"
    if r >= 0.9:
        return "FOCUSED"
    if r >= 0.7:
        return "CALM"
    if r >= 0.5:
        return "NERVOUS"
    if r >= 0.2:
        return "PANIC"
    return "DESPERATE"


def _thinking(p: Portfolio) -> bool:
    with _controller_lock:
        return _state.get("thinking", False)


def _cycle(p: Portfolio) -> int:
    for e in reversed(p.agent_log):
        if "=== CYCLE" in e["message"] and "START" in e["message"]:
            try:
                return int(e["message"].split("CYCLE")[1].split("START")[0].strip())
            except Exception:
                pass
    return 0
