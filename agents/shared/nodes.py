"""agents.shared.nodes — shared helpers, nodes, DB, sim engine extracted from agent.py."""

import asyncio
import json
import logging
import math
import random
import re
import threading
import time
import uuid as _uuid_mod
from datetime import datetime, date, timedelta

import pandas as pd
import yfinance as yf

try:
    import tweepy

    _HAS_TWEEPY = True
except ImportError:
    _HAS_TWEEPY = False

from config import (
    EVAL_HORIZON_CALENDAR_DAYS,
    INITIAL_BALANCE,
    MAX_ALLOC_PCT,
    MAX_POSITIONS,
    SIM_DRIFT,
    SIM_VOLATILITY,
    STOP_LOSS_PCT,
    WATCHLIST,
    X_BEARER_TOKEN,
)
from core.data import Portfolio
from agents.shared.state import AgentState
from agents.shared.prompts import PROMPT_VERSION
from agents.shared.llm import (
    HAIKU_ID,
    SONNET_ID,
    _llm,
    _maybe_reset_token_counter,
    _token_counter,
    get_llm_degradation_status,
    haiku,
    sonnet,
)
from agents.shared.db import (
    DB_PATH,
    _db_read,
    _db_write,
    _db_write_multi,
    _db_write_returning_id,
    _ensure_db,
    _init_db,
)
from agents.shared.eval import (
    EVAL_SIGNIFICANCE_PCT,
    _fast_last_price,
    evaluate_pending_trades,
)
from agents.shared.modes import (
    _no_llm_mode,
    _paper_mode,
    _sim_mode,
    get_paper_mode,
    get_runtime_mode,
    get_simulation_mode,
    set_paper_mode,
    set_simulation_mode,
    _write_env_var,
)


def _get_db_path():
    """Delegate to ``agents.shared.db`` so tests can patch ``db._get_db_path`` reliably."""
    from agents.shared import db as _db

    return _db._get_db_path()


logger = logging.getLogger("apex7")

# ── Helpers ──────────────────────────────────────────────────────────────────


def _ts() -> str:
    return datetime.now().isoformat()


def _entry(message: str, level: str = "info") -> dict:
    return {"time": _ts(), "message": message, "level": level}


def _parse_json_obj(text: str) -> dict:
    """Extract first valid JSON object from text (depth-aware)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("{")
    if start == -1:
        return {}
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


# ── Daily P&L baseline (first agent cycle per calendar day) ─────────────────

_daily_start_value: dict = {"value": None, "date": None}
_daily_start_lock = threading.Lock()


def maybe_update_daily_start(portfolio: Portfolio, prices: dict[str, float]) -> None:
    """Record ``total_value`` on the first ``execute`` cycle of each calendar day."""

    today = date.today().isoformat()
    with _daily_start_lock:
        if _daily_start_value["date"] != today:
            _daily_start_value["date"] = today
            _daily_start_value["value"] = float(portfolio.total_value(prices))


def get_daily_start_value() -> tuple[float | None, str | None]:
    """Return ``(start_value, date_iso)`` for today's daily P&L baseline, if any."""

    with _daily_start_lock:
        return (
            _daily_start_value["value"],
            _daily_start_value["date"],
        )


def _week_monday(d: date) -> date:
    """Monday of the ISO calendar week containing ``d`` (``weekday()`` Mon=0)."""

    return d - timedelta(days=d.weekday())


_weekly_start_value: dict = {"value": None, "week_key": None}
_weekly_start_lock = threading.Lock()


def maybe_update_weekly_start(portfolio: Portfolio, prices: dict[str, float]) -> None:
    """Record ``total_value`` on the first ``execute`` cycle of each ISO week."""

    monday = _week_monday(date.today())
    wk = monday.isoformat()
    with _weekly_start_lock:
        if _weekly_start_value["week_key"] != wk:
            _weekly_start_value["week_key"] = wk
            _weekly_start_value["value"] = float(portfolio.total_value(prices))


def get_weekly_start_value() -> tuple[float | None, str | None]:
    """Return ``(start_value, monday_iso)`` for the current week's baseline, if any."""

    with _weekly_start_lock:
        return (
            _weekly_start_value["value"],
            _weekly_start_value["week_key"],
        )


# ── HOLD stagnation (Finding 3.5) ──────────────────────────────────────────────

_consecutive_holds = 0
_hold_stagnation_lock = threading.Lock()


def get_consecutive_hold_cycles() -> int:
    """Return the count of consecutive cycles whose final decision action was HOLD."""
    with _hold_stagnation_lock:
        return _consecutive_holds


def _record_hold_stagnation(final_action: str) -> None:
    """Increment on HOLD, reset on BUY/SELL; warn after 10 consecutive HOLD cycles."""
    global _consecutive_holds
    action_u = (final_action or "HOLD").upper()
    with _hold_stagnation_lock:
        if action_u == "HOLD":
            _consecutive_holds += 1
            n = _consecutive_holds
        else:
            _consecutive_holds = 0
            n = 0
    if action_u == "HOLD" and n >= 10:
        logger.warning(
            "HOLD stagnation: %d consecutive HOLD cycles — consider pausing agent",
            n,
        )
        if n == 10 and not get_simulation_mode():
            try:
                from core.notifications import alert_stagnation

                alert_stagnation(hold_cycles=n)
            except Exception:
                pass


# ── Market data (async parallel) ─────────────────────────────────────────────

_prev_prices: dict[str, float] = {}


def _fetch_prices_sync(portfolio: Portfolio) -> dict[str, float]:
    return portfolio.fetch_prices()


def _fetch_news_sync(symbols: list[str]) -> str:
    parts: list[str] = []
    for sym in symbols[:3]:
        try:
            items = yf.Ticker(sym).news or []
            for item in items[:3]:
                title = item.get("title") or (item.get("content") or {}).get("title", "")
                if title:
                    parts.append(f"[{sym}] {title}")
        except Exception:
            pass
    return "\n".join(parts) if parts else "No news available"


def _fetch_sentiment_sync(symbols: list[str]) -> dict[str, float]:
    if _HAS_TWEEPY and X_BEARER_TOKEN:
        try:
            tc = tweepy.Client(bearer_token=X_BEARER_TOKEN)
            pos_w = {"buy", "bull", "up", "moon", "strong", "surge", "breakout"}
            neg_w = {"sell", "bear", "down", "crash", "weak", "short", "dump"}
            result: dict[str, float] = {}
            for sym in symbols:
                resp = tc.search_recent_tweets(
                    query=f"${sym} stock -is:retweet lang:en",
                    max_results=10,
                )
                score, count = 0, 0
                if resp.data:
                    for tw in resp.data:
                        words = set(tw.text.lower().split())
                        score += len(words & pos_w) - len(words & neg_w)
                        count += 1
                result[sym] = round(max(min(score / max(count, 1), 1.0), -1.0), 2)
            return result
        except Exception:
            pass
    return {sym: round(random.uniform(-0.3, 0.3), 2) for sym in symbols}


async def _gather_data(portfolio: Portfolio, news_syms: list[str]) -> tuple[dict, str, dict]:
    loop = asyncio.get_running_loop()
    prices, news, sentiment = await asyncio.gather(
        loop.run_in_executor(None, _fetch_prices_sync, portfolio),
        loop.run_in_executor(None, _fetch_news_sync, news_syms),
        loop.run_in_executor(None, _fetch_sentiment_sync, WATCHLIST),
    )
    return prices, news, sentiment


def _run_async(coro) -> tuple:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _is_flat(prices: dict[str, float], threshold: float = 0.005) -> bool:
    if not _prev_prices or not prices:
        return False
    return all(
        abs(prices[s] - _prev_prices[s]) / max(_prev_prices[s], 0.01) < threshold
        for s in prices
        if s in _prev_prices
    )


def _portfolio_value(state) -> float:
    return state["balance"] + sum(
        pos["shares"] * state["prices"].get(sym, pos.get("avg_price", pos.get("avg_cost", 0)))
        for sym, pos in state["positions"].items()
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

_SIM_NEWS_TEMPLATES = [
    "Strong momentum detected on {sym} — volume surge",
    "Bearish divergence on RSI for {sym}, caution advised",
    "Earnings beat expectations — {sym} up pre-market",
    "Macro headwinds persist, {sym} under selling pressure",
    "Breakout confirmed on {sym} with above-average volume",
    "Analysts upgrade {sym} price target by 12%",
    "Short interest rising sharply on {sym}",
    "Institutional accumulation detected on {sym}",
    "{sym} testing key resistance — watch for rejection",
    "Momentum fading on {sym} — overbought conditions",
]

_SIM_THOUGHTS = {
    "BUY": "RSI oversold, risk/reward favorable. Entering position with discipline.",
    "SELL": "RSI overbought, locking in gains before reversal. Cash is a position.",
    "HOLD": "No clear edge. Preserving capital until setup aligns.",
}

# Per-symbol simulated price history (for RSI computation)
_sim_price_history: dict[str, list[float]] = {}

# Per-symbol live closes for RSI (multi-agent technician); filled in fetch_data_node (live path)
_live_price_history: dict[str, list[float]] = {}
_live_price_history_seeded: bool = False
_last_price_date: dict[str, str] = {}
_live_price_history_lock = threading.Lock()


def _seed_live_price_history() -> None:
    """One-time seed from ~1mo daily closes so RSI(14) is meaningful from cycle 1."""
    global _live_price_history_seeded
    with _live_price_history_lock:
        if _live_price_history_seeded:
            return
        for sym in WATCHLIST:
            try:
                df = yf.download(
                    sym,
                    period="1mo",
                    interval="1d",
                    progress=False,
                    auto_adjust=True,
                )
                if df is None or len(df) == 0:
                    logger.warning("No OHLC data to seed for %s", sym)
                    continue
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.copy()
                    df.columns = df.columns.get_level_values(0)
                closes = [float(x) for x in df["Close"].dropna().tolist()]
                if not closes:
                    continue
                _live_price_history[sym] = closes[-60:]
                logger.info(
                    "Seeded _live_price_history for %s with %d daily closes",
                    sym,
                    len(_live_price_history[sym]),
                )
                idx = df.index[-1]
                if hasattr(idx, "date"):
                    _last_price_date[sym] = idx.date().isoformat()
                else:
                    _last_price_date[sym] = str(idx)[:10]
            except Exception as e:
                logger.warning("Seed failed for %s: %s", sym, e)
        _live_price_history_seeded = True


def _record_live_prices_for_rsi(prices: dict[str, float]) -> None:
    """Append at most one close per symbol per calendar day; cap at 60 bars."""
    if not _live_price_history_seeded:
        _seed_live_price_history()
    today = date.today().isoformat()
    for sym in WATCHLIST:
        if sym not in prices:
            continue
        try:
            pf = float(prices[sym])
        except (TypeError, ValueError):
            continue
        if math.isnan(pf) or pf <= 0:
            continue
        if _last_price_date.get(sym) == today:
            continue
        hist = _live_price_history.setdefault(sym, [])
        hist.append(pf)
        _last_price_date[sym] = today
        if len(hist) > 60:
            _live_price_history[sym] = hist[-60:]


def _sim_step_prices(current: dict[str, float]) -> dict[str, float]:
    """Random-walk one step for each symbol."""
    drift = _sim_mode.get("drift", SIM_DRIFT)
    vol = _sim_mode.get("volatility", SIM_VOLATILITY)
    new_prices: dict[str, float] = {}
    for sym, price in current.items():
        change = random.gauss(drift, vol)
        new_prices[sym] = max(price * (1 + change), 0.01)
        _sim_price_history.setdefault(sym, [price]).append(new_prices[sym])
        if len(_sim_price_history[sym]) > 100:  # keep last 100
            _sim_price_history[sym] = _sim_price_history[sym][-100:]
    return new_prices


def _sim_seed_prices(watchlist: list[str], last_known: dict[str, float]) -> dict[str, float]:
    """Seed sim prices from last known real prices or reasonable defaults."""
    defaults = {"AAPL": 185.0, "MSFT": 415.0, "GOOG": 165.0, "AMZN": 185.0, "TSLA": 250.0}
    return {s: last_known.get(s) or defaults.get(s, 100.0) for s in watchlist}


def sim_fetch_data(state: AgentState, portfolio: Portfolio) -> dict:
    """Simulation version of fetch_data — zero network calls."""
    logs = [_entry("fetch_data: using simulation")]

    current = dict(portfolio.last_prices) or {}
    if not all(s in current for s in WATCHLIST):
        current = _sim_seed_prices(WATCHLIST, current)

    prices = _sim_step_prices(current)
    news_syms = list(state["positions"].keys())[:3] or WATCHLIST[:3]
    news = "\n".join(random.choice(_SIM_NEWS_TEMPLATES).format(sym=s) for s in news_syms)
    sentiment = {s: round(random.uniform(-1, 1), 2) for s in WATCHLIST}

    # Update portfolio's cached prices so execute_node has values
    with portfolio._lock:
        portfolio.last_prices = prices

    flat = _is_flat(prices)
    _prev_prices.update(prices)
    logs.append(_entry(f"[SIM] prices={prices} | flat={flat}"))

    return {
        "prices": prices,
        "news": news,
        "sentiment": sentiment,
        "skip_research": flat,
        "log": logs,
    }


def sim_research(state: AgentState) -> dict:
    """In simulation mode, research is skipped — confidence forced to 0.75."""
    sym = (state.get("decision") or {}).get("symbol", "")
    return {
        "research_iterations": state["research_iterations"] + 1,
        "confidence": 0.75,
        "decision": {**(state.get("decision") or {}), "confidence": 0.75},
        "log": [_entry(f"[SIM] research: skipped for {sym} — confidence bumped to 0.75")],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NODES
# ═══════════════════════════════════════════════════════════════════════════════


def load_memory_node(state: AgentState) -> dict:
    logs = [_entry("load_memory: querying SQLite...")]

    rows = _db_read(
        "SELECT timestamp,symbol,action,price,amount_usd,shares,"
        "reasoning,confidence,emotion,portfolio_value_after,lesson,trace_id,source,prompt_version,"
        "sell_pct "
        "FROM trades ORDER BY timestamp DESC LIMIT 20"
    )

    cols = (
        "timestamp",
        "symbol",
        "action",
        "price",
        "amount_usd",
        "shares",
        "reasoning",
        "confidence",
        "emotion",
        "portfolio_value_after",
        "lesson",
        "trace_id",
        "source",
        "prompt_version",
        "sell_pct",
    )
    past_trades = [dict(zip(cols, row)) for row in rows]

    if not past_trades:
        logs.append(_entry("load_memory: no history yet"))
        return {"past_trades": [], "known_patterns": [], "log": logs}

    # Sim and paper skip the LLM pattern extraction (no Anthropic call).
    if _no_llm_mode():
        patterns = [t["lesson"] for t in past_trades if t.get("lesson")][:5]
        tag = "PAPER" if _paper_mode["enabled"] else "SIM"
        logs.append(_entry(f"[{tag}] load_memory: {len(past_trades)} trades (no LLM analysis)"))
        return {"past_trades": past_trades, "known_patterns": patterns, "log": logs}

    prompt = (
        "Analyse ces trades récents et identifie les patterns, erreurs répétées, ou succès :\n"
        f"{json.dumps(past_trades[:10], indent=2, default=str)}\n\n"
        "Retourne UNIQUEMENT un JSON array de strings, chaque string décrit un pattern "
        '(max 15 mots). Exemple : ["Achète AAPL trop tôt après correction", ...]'
    )
    text = _llm(haiku, HAIKU_ID, [{"role": "user", "content": prompt}], max_tokens=512)

    patterns: list[str] = []
    m = re.search(r"\[[\s\S]*?\]", text)
    if m:
        try:
            patterns = [str(p) for p in json.loads(m.group())]
        except Exception:
            pass

    logs.append(_entry(f"load_memory: {len(past_trades)} trades, {len(patterns)} patterns"))
    return {"past_trades": past_trades, "known_patterns": patterns, "log": logs}


def make_fetch_data_node(portfolio: Portfolio):
    def fetch_data_node(state: AgentState) -> dict:
        if _sim_mode["enabled"]:
            return sim_fetch_data(state, portfolio)

        logs = [_entry("fetch_data: using LiveFeed")]

        pos = state["positions"]
        news_syms = (
            sorted(pos, key=lambda s: pos[s]["shares"] * state["prices"].get(s, 0), reverse=True)[
                :3
            ]
            if pos
            else WATCHLIST[:3]
        )

        try:
            prices, news, sentiment = _run_async(_gather_data(portfolio, news_syms))
        except Exception as e:
            logs.append(_entry(f"fetch_data error: {e}", "error"))
            prices = dict(portfolio.last_prices)
            news = "Fetch failed"
            sentiment = {s: 0.0 for s in WATCHLIST}

        flat = _is_flat(prices)
        _prev_prices.update(prices)

        _record_live_prices_for_rsi(prices)

        logs.append(
            _entry(
                f"fetch_data: {len(prices)} prices | news={len(news)}ch | "
                f"sentiment={sentiment} | flat={flat}"
            )
        )
        return {
            "prices": prices,
            "news": news,
            "sentiment": sentiment,
            "skip_research": flat,
            "log": logs,
        }

    return fetch_data_node


def research_node(state: AgentState) -> dict:
    if _no_llm_mode():
        return sim_research(state)

    decision = state.get("decision") or {}
    symbol = decision.get("symbol") or ""
    reasoning = decision.get("reasoning") or ""
    it = state["research_iterations"] + 1
    logs = [_entry(f"research #{it}: deep-dive on {symbol}")]

    prompt = (
        f"Recherche approfondie sur : {symbol} — {reasoning}\n\n"
        "Fournis en 5-6 phrases : catalyseurs récents, risques, sentiment marché, "
        "niveau technique clé (support/résistance), consensus analystes si dispo. "
        "Sois factuel et concis."
    )
    text = _llm(
        sonnet, SONNET_ID, [{"role": "user", "content": prompt}], max_tokens=2048, web_search=True
    )

    logs.append(_entry(f"research #{it}: {len(text)} chars gathered for {symbol}"))
    return {
        "news": state["news"] + f"\n\n─── RESEARCH #{it} [{symbol}] ───\n{text}",
        "research_iterations": it,
        "log": logs,
    }


def risk_check_node(state: AgentState) -> dict:
    decision = state.get("decision") or {}
    action = decision.get("action", "HOLD").upper()
    symbol = decision.get("symbol") or ""
    alloc = float(decision.get("allocation_pct", 10))
    sell_pct = float(decision.get("sell_pct", 100))
    prices = state["prices"]
    pos = state["positions"]
    balance = state["balance"]
    pv = _portfolio_value(state)

    failures: list[str] = []

    if action == "BUY":
        # Silently clamp allocation
        if alloc > MAX_ALLOC_PCT:
            decision = {**decision, "allocation_pct": MAX_ALLOC_PCT}
            alloc = MAX_ALLOC_PCT
        amount = pv * (alloc / 100)
        if amount > balance:
            failures.append(f"cash insuffisant (besoin ${amount:.0f} > dispo ${balance:.0f})")
        if len(pos) >= MAX_POSITIONS and symbol not in pos:
            failures.append(f"max {MAX_POSITIONS} positions atteint")
        if not symbol or symbol not in prices:
            failures.append(f"symbol invalide ou absent du watchlist : {symbol!r}")
        if pv < INITIAL_BALANCE * 0.7:
            failures.append(f"danger zone (${pv:.0f} < ${INITIAL_BALANCE * 0.7:.0f}) — BUY bloqué")

    elif action == "SELL":
        if symbol not in pos:
            failures.append(f"aucune position sur {symbol}")
        if not 0 < sell_pct <= 100:
            failures.append(f"sell_pct invalide : {sell_pct}")

    passed = len(failures) == 0
    reason = " | ".join(failures)

    logs = [
        _entry(
            f"risk_check: {'✓ PASS' if passed else '✗ FAIL — ' + reason}",
            level="info" if passed else "warning",
        )
    ]
    return {
        "decision": {**decision, "_risk_passed": passed, "_risk_reason": reason},
        "log": logs,
    }


def make_execute_node(portfolio: Portfolio):
    def execute_node(state: AgentState) -> dict:
        decision = state.get("decision") or {}
        action = decision.get("action", "HOLD").upper()
        symbol = decision.get("symbol") or ""
        alloc = float(decision.get("allocation_pct", 10))
        sell_pct = float(decision.get("sell_pct", 100))
        prices = state["prices"]
        maybe_update_daily_start(portfolio, prices)
        maybe_update_weekly_start(portfolio, prices)
        pv = portfolio.total_value(prices)
        logs = [_entry(f"execute: {action} {symbol}")]

        result: dict = {"success": False, "error": "no-op"}

        portfolio.update_watermarks(prices)

        # Trailing stop-loss on all open positions (drawdown from high watermark).
        for sl_sym, sl_pos in list(portfolio.positions.items()):
            sl_price = prices.get(sl_sym, 0.0)
            sl_avg = sl_pos.get("avg_price", sl_pos.get("avg_cost", 0))
            try:
                savg = float(sl_avg)
            except (TypeError, ValueError):
                continue
            if math.isnan(savg) or savg <= 0:
                continue
            try:
                sp = float(sl_price)
            except (TypeError, ValueError):
                logger.warning(
                    "Skipping stop-loss for %s: invalid price %s",
                    sl_sym,
                    sl_price,
                )
                continue
            if math.isnan(sp) or sp <= 0:
                logger.warning(
                    "Skipping stop-loss for %s: invalid price %s",
                    sl_sym,
                    sl_price,
                )
                continue
            # Sub-dollar legitimate positions: allow SL when basis and quote are both cheap.
            penny_pair = savg <= 1.0 and sp <= 1.0
            plausible_quote = sp > 1.0 or penny_pair
            if not plausible_quote:
                logs.append(
                    _entry(
                        f"Skipping stop-loss check for {sl_sym}: invalid price "
                        f"sl_price={sp}, sl_avg={savg}",
                        "warning",
                    )
                )
                continue
            try:
                high = float(portfolio.high_watermarks.get(sl_sym, savg))
            except (TypeError, ValueError):
                high = savg
            if math.isnan(high) or high <= 0:
                high = savg
            trail_dd = (high - sp) / high if high > 0 else 0.0
            if trail_dd >= STOP_LOSS_PCT:
                sl_slip = 1 + random.uniform(-0.001, 0.001)
                exit_px = sp * sl_slip
                portfolio.sell(sl_sym, 100, exit_px)
                try:
                    from core.notifications import alert_trailing_stop

                    alert_trailing_stop(
                        symbol=sl_sym,
                        price=exit_px,
                        high_watermark=high,
                        drawdown_pct=trail_dd,
                    )
                except Exception:
                    pass
                logs.append(
                    _entry(
                        f"[TRAILING STOP] triggered: {sl_sym} @ ${sp:.2f} "
                        f"(high ${high:.2f}, drawdown {trail_dd:.1%})",
                        "warning",
                    )
                )

        if action == "BUY" and symbol in prices:
            slip = 1 + random.uniform(-0.001, 0.001)
            price = prices[symbol] * slip
            amount = pv * (min(alloc, MAX_ALLOC_PCT) / 100)
            result = portfolio.buy(symbol, amount, price)
            if result["success"]:
                logs.append(
                    _entry(
                        f"BUY {symbol} {result['shares']:.5f} sh @ ${price:.2f} "
                        f"= ${result['amount']:.2f}  slip={slip-1:+.3%}"
                    )
                )

        elif action == "SELL" and symbol:
            slip = 1 + random.uniform(-0.001, 0.001)
            price = prices.get(symbol, 0) * slip
            result = portfolio.sell(symbol, sell_pct, price)
            if result["success"]:
                # Surface partial-exit percentage in the activity log
                # (Review v5 Finding 6.3). Full exits keep the compact form.
                sym_label = f"{sell_pct:.0f}% {symbol}" if sell_pct < 100 else symbol
                logs.append(
                    _entry(
                        f"SELL {sym_label} @ ${price:.2f} "
                        f"= ${result['amount']:.2f}  slip={slip-1:+.3%}"
                    )
                )

        elif action == "HOLD":
            logs.append(_entry(f"HOLD — {decision.get('reasoning','')[:100]}"))
            result = {"success": True}

        if not result.get("success"):
            logs.append(_entry(f"execute failed: {result.get('error', '?')}", "warning"))

        portfolio.record_value(prices)
        portfolio.check_death(prices)
        new_pv = portfolio.total_value(prices)

        return {
            "balance": portfolio.cash,
            "positions": dict(portfolio.positions),
            "portfolio_history": [new_pv],
            "alive": not portfolio.is_dead,
            "log": logs,
        }

    return execute_node


def _discord_votes_summary(state: AgentState) -> str | None:
    """Short multi-line summary of specialist votes for Discord (compact)."""
    arb = state.get("arbitration")
    if isinstance(arb, dict):
        votes = arb.get("_votes")
        if votes:
            lines = [
                f"{v.get('agent', '?')}: {v.get('action', '?')} "
                f"{v.get('symbol', '')} ({float(v.get('confidence', 0)):+.0%})"
                for v in votes
            ]
            return "\n".join(lines)[:1024]
    votes = state.get("agent_votes") or []
    if votes:
        lines = [
            f"{v.get('agent', '?')}: {v.get('action', '?')} "
            f"{v.get('symbol', '')} ({float(v.get('confidence', 0)):+.0%})"
            for v in votes
        ]
        return "\n".join(lines)[:1024]
    parts: list[str] = []
    for key, label in (
        ("tech_vote", "technician"),
        ("analyst_vote", "analyst"),
        ("risk_vote", "risk_manager"),
        ("macro_vote", "macro_watcher"),
    ):
        v = state.get(key)
        if isinstance(v, dict):
            parts.append(
                f"{label}: {v.get('action', '?')} {v.get('symbol', '')} "
                f"({float(v.get('confidence', 0)):+.0%})"
            )
    return "\n".join(parts)[:1024] if parts else None


def make_save_memory_node(portfolio: Portfolio):
    def save_memory_node(state: AgentState) -> dict:
        decision = state.get("decision") or {}
        action = decision.get("action", "HOLD").upper()
        _record_hold_stagnation(action)
        logs = [_entry("save_memory: persisting...")]

        if action == "HOLD":
            logs.append(_entry("save_memory: HOLD — skipped"))
            return {"log": logs}

        symbol = decision.get("symbol") or ""
        prices = state["prices"]
        price = prices.get(symbol, 0.0)
        pv_after = portfolio.total_value(prices)

        last_trade = next(
            (t for t in reversed(portfolio.trade_history) if t.get("symbol") == symbol), {}
        )
        shares = last_trade.get("shares", 0.0)
        amount = last_trade.get("amount", 0.0)

        source = get_runtime_mode()  # 'live' | 'paper' | 'sim' → 'simulation'
        if source == "sim":
            source = "simulation"

        if _no_llm_mode():
            tag = "PAPER" if _paper_mode["enabled"] else "SIM"
            lesson = f"[{tag}] {action} {symbol} @ ${price:.2f} — RSI-based signal"
        else:
            lesson_prompt = (
                f"En une phrase concise (max 15 mots), quelle leçon retenir de ce trade ?\n"
                f"Action: {action} {symbol} @ ${price:.2f} | "
                f"Conf: {decision.get('confidence', 0):.0%} | "
                f"Émotion: {state['emotion']} | "
                f"Portfolio après: ${pv_after:.2f}"
            )
            lesson = _llm(
                haiku, HAIKU_ID, [{"role": "user", "content": lesson_prompt}], max_tokens=80
            ).strip()

        ts = _ts()
        trace_id = _get_trace_id()
        trade_id = _db_write_returning_id(
            "INSERT INTO trades "
            "(timestamp,symbol,action,price,amount_usd,shares,"
            "reasoning,confidence,emotion,portfolio_value_after,lesson,trace_id,source,"
            "prompt_version,sell_pct) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ts,
                symbol,
                action,
                price,
                amount,
                shares,
                decision.get("reasoning", ""),
                float(decision.get("confidence", 0.0)),
                state["emotion"],
                pv_after,
                lesson,
                trace_id,
                source,
                PROMPT_VERSION,
                float(decision.get("sell_pct", 100.0)) if action == "SELL" else None,
            ),
        )
        if trade_id is None:
            logs.append(_entry("save_memory: trades INSERT failed", "error"))
        else:
            try:
                from core.notifications import alert_trade

                summary = _discord_votes_summary(state)
                alert_trade(
                    symbol=symbol,
                    action=action,
                    price=float(price),
                    amount_usd=float(amount) if amount else None,
                    sell_pct=float(decision.get("sell_pct", 100.0)) if action == "SELL" else None,
                    confidence=float(decision.get("confidence", 0.0)),
                    votes_summary=summary,
                )
            except Exception:
                pass
            entry_dt = datetime.fromisoformat(ts) if "T" in ts else datetime.now()
            eval_after = (entry_dt + timedelta(days=EVAL_HORIZON_CALENDAR_DAYS)).isoformat()
            ok_pending = _db_write(
                "INSERT INTO pending_evaluations "
                "(trade_id,trace_id,symbol,action,entry_price,entry_date,eval_after_date,evaluated) "
                "VALUES (?,?,?,?,?,?,?,0)",
                (trade_id, trace_id, symbol, action, price, ts, eval_after),
            )
            if not ok_pending:
                logs.append(_entry("save_memory: pending_evaluations INSERT failed", "error"))

        ok_pattern = _db_write(
            "INSERT INTO patterns (timestamp, pattern) VALUES (?,?)",
            (ts, lesson),
        )
        if not ok_pattern:
            logs.append(_entry("save_memory: patterns INSERT failed", "error"))

        logs.append(_entry(f"save_memory: lesson → {lesson[:90]}"))
        return {
            "known_patterns": state["known_patterns"] + [lesson],
            "log": logs,
        }

    return save_memory_node


def skip_node(state: AgentState) -> dict:
    decision = state.get("decision") or {}
    action = decision.get("action", "HOLD").upper()
    _record_hold_stagnation(action)
    reason = decision.get("_risk_reason") or "trade rejected by risk_check"
    return {"log": [_entry(f"skip: {reason}", "warning")]}


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════════════════════


def _route_risk(state) -> str:
    decision = state.get("decision") or {}
    if "_risk_passed" not in decision:
        logger.warning("risk_check_node did not set _risk_passed — defaulting to skip")
    passed = decision.get("_risk_passed", False)
    return "execute" if passed else "skip"


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT STATUS  (read by Dash)
# ═══════════════════════════════════════════════════════════════════════════════

_agent_status: dict = {
    "cycle": 0,
    "emotion": "CALM",
    "thoughts": "",
    "confidence": 0.0,
    "decision": None,
    "research_iterations": 0,
    "alive": True,
    "last_update": None,
}

_trace_id: dict = {"current": ""}


def _new_trace_id() -> str:
    """Generate a new trace ID for a cycle."""
    tid = _uuid_mod.uuid4().hex[:8]
    _trace_id["current"] = tid
    return tid


def _get_trace_id() -> str:
    return _trace_id["current"]


def get_agent_status() -> dict:
    return dict(_agent_status)
