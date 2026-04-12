"""APEX-7 — Agent controller: agent loop, portfolio state, postmortem thread."""

import logging
import threading
import time
from datetime import datetime

from agents.shared.nodes import _new_trace_id, get_simulation_mode
from agents.multi import run_daily_postmortem
from config import AGENT_GRAPH, AGENT_INTERVAL, POSTMORTEM_HOUR
from core.data import Portfolio
from core.registry import get_graph

logger = logging.getLogger("apex7.controller")

# ═══════════════════════════════════════════════════════════════════════════════
# AGENT CONTROLLER STATE
# ═══════════════════════════════════════════════════════════════════════════════

_ctrl: dict = {"paused": False, "step": False, "cycle": 0, "sim_mode": False}
_state: dict = {
    "graph_id": AGENT_GRAPH,
    "last_votes": [],
    "last_arb": {},
    "thinking": False,
}


def _agent_loop(p: Portfolio, graph_id: str = "simple") -> None:
    import traceback

    graph = get_graph(graph_id, p)
    cycle = 0
    is_multi = graph_id == "multi"

    while not p.is_dead:
        while _ctrl["paused"] and not _ctrl["step"] and not p.is_dead:
            time.sleep(0.3)
        if p.is_dead:
            break
        _ctrl["step"] = False
        cycle += 1
        _ctrl["cycle"] = cycle
        _ctrl["sim_mode"] = get_simulation_mode()
        trace_id = _new_trace_id()
        logger.info("[%s] === CYCLE %d START ===", trace_id, cycle)
        p.log(f"=== CYCLE {cycle} START ===")
        try:
            initial: dict = {
                "balance": p.cash,
                "positions": dict(p.positions),
                "portfolio_history": [],
                "prices": dict(p.last_prices),
                "news": "",
                "sentiment": {},
                "past_trades": [],
                "known_patterns": [],
                "round": cycle,
                "confidence": 0.0,
                "research_iterations": 0,
                "decision": None,
                "emotion": "CALM",
                "thoughts": "",
                "log": [],
                "alive": True,
                "skip_research": False,
            }
            if is_multi:
                initial.update(
                    {
                        "supervisor_brief": "",
                        "agent_role": "",
                        "agent_votes": [],
                        "tech_vote": None,
                        "analyst_vote": None,
                        "risk_vote": None,
                        "macro_vote": None,
                        "arbitration": None,
                    }
                )
            _state["thinking"] = True
            result = graph.invoke(initial)
            _state["thinking"] = False
            for entry in result.get("log", []):
                p.log(entry["message"], entry.get("level", "info"))
            if is_multi:
                _state["last_votes"] = result.get("agent_votes", [])
                _state["last_arb"] = result.get("arbitration", {}) or {}
            if not result.get("alive", True):
                p.is_dead = True
                p.log("DEATH CONDITION MET", "critical")
                break
        except Exception as e:
            p.log(f"Cycle error: {e}", "error")
            p.log(traceback.format_exc(), "error")
        if p.is_dead:
            p.log("AGENT HALTED — DEATH CONDITION MET", "critical")
            break
        sleep_s = 3 if get_simulation_mode() else AGENT_INTERVAL
        p.log(f"=== CYCLE {cycle} DONE — sleeping {sleep_s}s ===")
        elapsed = 0.0
        while elapsed < sleep_s and not p.is_dead:
            if _ctrl["paused"] and not _ctrl["step"]:
                time.sleep(0.3)
            else:
                time.sleep(1.0)
                elapsed += 1.0


def _launch(p: Portfolio, graph_id: str = "simple") -> threading.Thread:
    t = threading.Thread(target=_agent_loop, args=(p, graph_id), daemon=True)
    t.start()
    return t


# ── Postmortem thread ─────────────────────────────────────────────────────────
_last_postmortem_date = None
_controller_lock = threading.Lock()
_controller_started = False


def start_controller() -> None:
    """Create the live portfolio and start agent + postmortem threads.

    Called explicitly from ``create_app()`` so importing this module does not
    spawn threads or construct ``Portfolio``.
    """
    global _controller_started
    with _controller_lock:
        if _controller_started:
            return
        _state["portfolio"] = Portfolio()
        _state["thread"] = _launch(_state["portfolio"], _state["graph_id"])
        threading.Thread(
            target=_postmortem_loop,
            args=(_state["portfolio"],),
            daemon=True,
            name="apex7-postmortem",
        ).start()
        _controller_started = True


def _postmortem_loop(p: Portfolio) -> None:
    global _last_postmortem_date
    while True:
        time.sleep(60)
        now = datetime.now()
        today = now.date()
        if now.hour == POSTMORTEM_HOUR and _last_postmortem_date != today:
            try:
                run_daily_postmortem(p)
                _last_postmortem_date = today
            except Exception as _e:
                p.log(f"Postmortem error: {_e}", "error")
