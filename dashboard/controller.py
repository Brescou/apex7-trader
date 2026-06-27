"""APEX-7 — Agent controller: agent loop, portfolio state, postmortem thread."""

import logging
import threading
import time
from datetime import datetime

from agents.shared.nodes import (
    _new_trace_id,
    evaluate_pending_trades,
    get_consecutive_hold_cycles,
    get_runtime_mode,
    get_simulation_mode,
)
from agents.shared.watchlist import get_watchlist
from agents.multi import run_daily_digest, run_daily_postmortem, run_weekly_report
from agents.registry import get_graph
from config import AGENT_INTERVAL, POSTMORTEM_HOUR
from core.data import Portfolio

logger = logging.getLogger("apex7.controller")

# ═══════════════════════════════════════════════════════════════════════════════
# AGENT CONTROLLER STATE
# ═══════════════════════════════════════════════════════════════════════════════

_ctrl: dict = {"paused": False, "step": False, "cycle": 0, "sim_mode": False}
_state: dict = {
    "last_votes": [],
    "last_arb": {},
    "thinking": False,
    "consecutive_holds": 0,
    "last_error": None,
    "_death_refresh_done": False,
}
# Single RLock for controller dicts — re-entrant so nested ``with`` in callbacks is safe.
_controller_lock = threading.RLock()
_controller_started = False


def _agent_loop(p: Portfolio) -> None:
    import traceback

    graph = get_graph(p)
    cycle = 0

    while not p.is_dead:
        while True:
            with _controller_lock:
                paused = _ctrl["paused"]
                step = _ctrl["step"]
            if p.is_dead:
                break
            if not (paused and not step):
                break
            time.sleep(0.3)
        if p.is_dead:
            break
        cycle += 1
        with _controller_lock:
            _ctrl["step"] = False
            _ctrl["cycle"] = cycle
            _ctrl["sim_mode"] = get_simulation_mode()
            _ctrl["mode"] = get_runtime_mode()
        trace_id = _new_trace_id()
        logger.info("[%s] === CYCLE %d START ===", trace_id, cycle)
        p.log(f"=== CYCLE {cycle} START ===")
        try:
            with _controller_lock:
                _state["last_error"] = None
            initial: dict = {
                "balance": p.cash,
                "positions": dict(p.positions),
                "portfolio_history": [],
                "prices": dict(p.last_prices),
                "news": "",
                "sentiment": {},
                "macro_indicators": {},
                "fear_greed": None,
                "earnings_calendar": {},
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
            with _controller_lock:
                _state["thinking"] = True
            result = graph.invoke(initial)
            with _controller_lock:
                _state["thinking"] = False
                _state["consecutive_holds"] = get_consecutive_hold_cycles()
                _state["last_votes"] = result.get("agent_votes", [])
                _state["last_arb"] = result.get("arbitration", {}) or {}
            for entry in result.get("log", []):
                p.log(entry["message"], entry.get("level", "info"))
            if not result.get("alive", True):
                p.is_dead = True
                p.log("DEATH CONDITION MET", "critical")
                break
        except Exception as e:
            with _controller_lock:
                _state["last_error"] = str(e)
            p.log(f"Cycle error: {e}", "error")
            p.log(traceback.format_exc(), "error")
        if p.is_dead:
            p.log("AGENT HALTED — DEATH CONDITION MET", "critical")
            break
        # Sim runs fast (random walk). Paper and live both pace at AGENT_INTERVAL
        # so the paper feedback loop matches live.
        sleep_s = 3 if get_simulation_mode() else AGENT_INTERVAL
        p.log(f"=== CYCLE {cycle} DONE — sleeping {sleep_s}s ===")
        elapsed = 0.0
        while elapsed < sleep_s and not p.is_dead:
            with _controller_lock:
                paused = _ctrl["paused"]
                step = _ctrl["step"]
            if paused and not step:
                time.sleep(0.3)
            else:
                time.sleep(1.0)
                elapsed += 1.0


def _launch(p: Portfolio) -> threading.Thread:
    t = threading.Thread(target=_agent_loop, args=(p,), daemon=True)
    t.start()
    return t


# ── Postmortem thread ─────────────────────────────────────────────────────────
_last_postmortem_date = None


def _run_digest_and_weekly_at_postmortem_hour(portfolio: Portfolio, now: datetime) -> None:
    """Run daily postmortem, digest, and weekly report (Sunday only) when hour matches."""

    global _last_postmortem_date
    today = now.date()
    if now.hour != POSTMORTEM_HOUR or _last_postmortem_date == today:
        return
    try:
        run_daily_postmortem(portfolio)
    except Exception as _e:
        portfolio.log(f"Postmortem error: {_e}", "error")
    try:
        run_daily_digest(portfolio)
    except Exception as _e:
        portfolio.log(f"Daily digest error: {_e}", "error")
    if now.weekday() == 6:
        try:
            run_weekly_report(portfolio)
        except Exception as _e:
            portfolio.log(f"Weekly report error: {_e}", "error")
    _last_postmortem_date = today


def _reconcile_portfolio_state(port: "Portfolio") -> None:
    """Compare JSON-loaded state with trades.db to detect divergence after crash.

    Reconstructs implied cash from the trade ledger and warns when it diverges
    from ``portfolio_state.json`` by more than $5 (rounding / commission tolerance).
    Purely diagnostic — never mutates the portfolio.
    """
    from config import INITIAL_BALANCE

    try:
        from agents.shared.db import _db_read, _ensure_db

        _ensure_db()
        rows = _db_read("SELECT action, amount_usd FROM trades ORDER BY id ASC")
    except Exception as exc:
        logger.warning("reconcile: could not read trades.db: %s", exc)
        return

    if not rows:
        return

    implied_cash = float(INITIAL_BALANCE)
    for action, amount_usd in rows:
        try:
            amt = float(amount_usd or 0)
        except (TypeError, ValueError):
            continue
        if action == "BUY":
            implied_cash -= amt
        elif action == "SELL":
            implied_cash += amt

    diff = abs(implied_cash - port.cash)
    if diff > 5.0:
        logger.warning(
            "Portfolio reconciliation: loaded cash=%.2f vs trades.db implied=%.2f "
            "(drift $%.2f) — possible crash recovery or commission mismatch",
            port.cash,
            implied_cash,
            diff,
        )
    else:
        logger.info(
            "Portfolio reconciliation OK: cash=%.2f (drift $%.2f)",
            port.cash,
            diff,
        )


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
        port = _state["portfolio"]
        if port.load_state():
            logger.info(
                "Portfolio state loaded from %s",
                (
                    port.PORTFOLIO_STATE_PATH
                    if hasattr(port, "PORTFOLIO_STATE_PATH")
                    else "portfolio_state.json"
                ),
            )
            _reconcile_portfolio_state(port)
        _state["thread"] = _launch(port)
        threading.Thread(
            target=_postmortem_loop,
            args=(port,),
            daemon=True,
            name="apex7-postmortem",
        ).start()
        _controller_started = True
    try:
        from core.notifications import alert_startup

        alert_startup(
            mode=str(get_runtime_mode() or "live"),
            watchlist_summary=", ".join(get_watchlist()),
        )
    except Exception:
        pass


def _postmortem_loop(p: Portfolio) -> None:
    while True:
        time.sleep(60)
        now = datetime.now()

        # Resolve any due pending trade evaluations every minute — independent
        # of the daily postmortem schedule. Skipped in simulation mode because
        # ``evaluate_pending_trades`` calls real yfinance. Paper mode uses real
        # quotes too, so it benefits from the same evaluation loop.
        if not get_simulation_mode():
            try:
                done = evaluate_pending_trades(now)
                if done:
                    logger.info("evaluate_pending_trades: completed %d evaluation(s)", done)
            except Exception as exc:
                p.log(f"evaluate_pending_trades error: {exc}", "error")

        _run_digest_and_weekly_at_postmortem_hour(p, now)
