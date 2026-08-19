"""APEX-7 // MULTI-AGENT GRAPH — 6 specialized agents + arbitration."""

import json
import logging
import math
import os
import random
import threading
import time
from datetime import datetime, date, timedelta

import yfinance as yf
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents.shared.nodes import (
    HAIKU_ID,
    SONNET_ID,
    EVAL_SIGNIFICANCE_PCT,
    _db_read,
    _db_write,
    _entry,
    _live_price_history,
    _get_trace_id,
    _llm,
    _parse_json_obj,
    _no_llm_mode,
    get_runtime_mode,
    _paper_mode,
    _portfolio_value,
    _route_risk,
    _sim_mode,
    _sim_price_history,
    _ts,
    haiku,
    load_memory_node,
    make_execute_node,
    make_fetch_data_node,
    make_save_memory_node,
    make_skip_node,
    research_node,
    risk_check_node,
    sonnet,
    get_weekly_start_value,
)
from agents.shared.prompts import (
    ANALYST_SYSTEM_PROMPT,
    ARBITRATE_SYSTEM_PROMPT,
    ECONOMIST_SYSTEM_PROMPT,
    GEOPOLITICIAN_SYSTEM_PROMPT,
    MACRO_WATCHER_SYSTEM_PROMPT,
    RISK_MANAGER_SYSTEM_PROMPT,
    TECHNICIAN_SYSTEM_PROMPT,
    UNTRUSTED_DATA_NOTICE,
)
from agents.shared.schemas import (
    validate_analyst_vote,
    validate_decision,
    validate_economist_vote,
    validate_geo_vote,
    validate_macro_vote,
    validate_risk_vote,
    validate_tech_vote,
)
from agents.shared.state import MultiAgentState
from config import (
    DEATH_THRESHOLD,
    INITIAL_BALANCE,
    MAX_ALLOC_PCT,
    MAX_POSITIONS,
)
from core.data import Portfolio
from core.indicators import rsi as _rsi
from core.metrics import kelly_fraction, win_stats
from agents.shared.watchlist import get_watchlist

logger = logging.getLogger("apex7.multi")

# ═══════════════════════════════════════════════════════════════════════════════
# WEIGHTS
# ═══════════════════════════════════════════════════════════════════════════════

# Poids statiques de chaque spécialiste dans la décision finale.
# Technician + Analyst votent sur la DIRECTION (BUY/SELL/HOLD) et portent 60 % du poids.
# Les 4 autres (Risk, Macro, Economist, Geo) ne votent pas sur la direction :
# ils contribuent au baseline HOLD et déclenchent des filtres de protection.
# Ces valeurs sont blendées dynamiquement avec la précision historique dès 5 trades évalués.
WEIGHTS = {
    "technician": 0.28,
    "analyst": 0.32,
    "risk_manager": 0.15,
    "macro_watcher": 0.10,
    "economist": 0.10,
    "geopolitician": 0.05,
}

# Map risk_manager sizing recommendation → SELL exit percentage.
# Used by ``arbitrate_node`` to derive a partial exit instead of always closing 100%.
SIZING_TO_SELL_PCT: dict[str, float] = {
    "FULL": 100.0,
    "HALF": 50.0,
    "QUARTER": 25.0,
    "SKIP": 0.0,
}

_cached_weights: dict = {}
_weights_computed_at: float = 0.0
# Dedicated lock for the cache + DB read; arbitrate_node may be entered
# concurrently by multiple cycles in tests / hot-reload scenarios.
_weights_lock = threading.Lock()
_WEIGHTS_CACHE_TTL_SEC = 600
_MIN_EVALUATED_VOTES = 5

# ── Slow-agent vote cache ─────────────────────────────────────────────────────
# Economist and Geopolitician consume Sonnet+web or heavy FRED data that
# changes slowly (FRED daily; geo on an hourly scale). Default 1 h so LIVE
# 15 min cycles reuse the last vote ~3 times instead of re-calling every tick.
_SLOW_AGENT_TTL_SEC = int(os.environ.get("SLOW_AGENT_TTL_SEC", "3600"))  # default 1 h
_slow_agent_cache: dict[str, dict] = {}  # agent_name → {"vote": dict, "ts": float}
_slow_agent_lock = threading.Lock()


def _get_cached_vote(agent_name: str) -> dict | None:
    """Return a cached vote if it is still within TTL, else None."""
    with _slow_agent_lock:
        entry = _slow_agent_cache.get(agent_name)
        if entry and (time.time() - entry["ts"]) < _SLOW_AGENT_TTL_SEC:
            return dict(entry["vote"])
        return None


def _set_cached_vote(agent_name: str, vote: dict) -> None:
    """Store a freshly computed vote in the slow-agent cache."""
    with _slow_agent_lock:
        _slow_agent_cache[agent_name] = {"vote": dict(vote), "ts": time.time()}


def _portfolio_correlation(target: str, held_symbols: list[str]) -> float:
    """Max absolute Pearson correlation between target symbol and any held position.

    Uses in-memory price histories (_live_price_history / _sim_price_history)
    so no extra network call is needed. Returns 0.0 when insufficient history.
    """
    import numpy as np

    hist = _sim_price_history if _sim_mode["enabled"] else _live_price_history
    target_hist = hist.get(target, [])
    if len(target_hist) < 10:
        return 0.0

    max_corr = 0.0
    for sym in held_symbols:
        if sym == target:
            return 1.0
        sym_hist = hist.get(sym, [])
        n = min(len(target_hist), len(sym_hist))
        if n < 10:
            continue
        try:
            a = np.array(target_hist[-n:], dtype=float)
            b = np.array(sym_hist[-n:], dtype=float)
            corr = abs(float(np.corrcoef(a, b)[0, 1]))
            if not math.isnan(corr):
                max_corr = max(max_corr, corr)
        except Exception:
            pass
    return max_corr


def _persist_cycle_state(
    cycle_num: int,
    arbitration: dict,
    votes: list[dict],
    action_scores: dict,
) -> None:
    """Write a compact JSON snapshot of the cycle decision for post-hoc replay.

    Keeps the last 200 rows (pruned every 50th cycle) so the table stays small.
    Fail-silent: a persistence error must never interrupt the trading loop.
    """
    try:
        snapshot = {
            "cycle": cycle_num,
            "action": arbitration.get("action"),
            "symbol": arbitration.get("symbol"),
            "confidence": round(float(arbitration.get("confidence", 0)), 3),
            "action_scores": {k: round(v, 3) for k, v in action_scores.items()},
            "votes": [
                {
                    "agent": v.get("agent", ""),
                    "action": v.get("action", ""),
                    "confidence": round(float(v.get("confidence", 0)), 3),
                    "symbol": v.get("symbol", ""),
                }
                for v in votes
            ],
        }
        source = _record_source()
        _db_write(
            "INSERT INTO cycle_states (timestamp, cycle_num, source, state_json) "
            "VALUES (?,?,?,?)",
            (_ts(), cycle_num, source, json.dumps(snapshot)),
        )
        if cycle_num % 50 == 0:
            _db_write(
                "DELETE FROM cycle_states WHERE id NOT IN "
                "(SELECT id FROM cycle_states ORDER BY id DESC LIMIT 200)",
                (),
            )
    except Exception as exc:
        logger.debug("cycle_state persistence failed: %s", exc)


def _read_agent_accuracies() -> dict[str, float | None]:
    """Magnitude-weighted vote accuracy per specialist.

    Each evaluated vote is weighted by the size of the subsequent price move
    (capped at 3× the significance threshold) so votes that were correct on
    large moves carry more signal than those correct on borderline moves.
    Falls back to equal-weight average for rows without ``eval_pct_change``.
    """
    agents = list(WEIGHTS.keys())
    accuracy: dict[str, float | None] = {}
    for agent in agents:
        rows = _db_read(
            "SELECT was_correct, COALESCE(eval_pct_change, ?) FROM agent_memory "
            "WHERE agent_name=? AND was_correct IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 50",
            (EVAL_SIGNIFICANCE_PCT, agent),
        )
        if len(rows) >= _MIN_EVALUATED_VOTES:
            # Weight = min(|move| / threshold, 3) — larger moves count up to 3×
            weights = [min(abs(float(r[1])) / EVAL_SIGNIFICANCE_PCT, 3.0) for r in rows]
            total_w = sum(weights) or 1.0
            accuracy[agent] = sum(int(r[0]) * w for r, w in zip(rows, weights)) / total_w
        else:
            accuracy[agent] = None
    return accuracy


def _compute_dynamic_weights() -> dict:
    """Compute agent weights blended with historical accuracy from agent_memory.

    Uses a 10-minute cache and is thread-safe via ``_weights_lock``. Falls
    back to static :data:`WEIGHTS` when an agent has fewer than
    ``_MIN_EVALUATED_VOTES`` evaluated votes; if **no** agent has any
    evaluated history yet (typical during the warm-up window where
    ``evaluate_pending_trades`` has not had time to fill ``was_correct``),
    returns the static weights verbatim.

    Blend formula for agents with enough history: ``0.7 * static + 0.3 * accuracy``.
    Result is always normalised to ``sum == 1.0``.
    """
    global _cached_weights, _weights_computed_at

    with _weights_lock:
        if _cached_weights and (time.time() - _weights_computed_at) < _WEIGHTS_CACHE_TTL_SEC:
            return dict(_cached_weights)

        agents = list(WEIGHTS.keys())
        try:
            accuracy = _read_agent_accuracies()
        except Exception as exc:
            logger.warning(
                "Dynamic weights: agent_memory read failed (%s) — falling back to static",
                exc,
            )
            _cached_weights = dict(WEIGHTS)
            _weights_computed_at = time.time()
            return dict(_cached_weights)

        evaluated = sum(1 for v in accuracy.values() if v is not None)
        pending = len(agents) - evaluated
        logger.info(
            "Dynamic weights: %d agents have evaluated history, %d agents pending",
            evaluated,
            pending,
        )

        if evaluated == 0:
            _cached_weights = dict(WEIGHTS)
            _weights_computed_at = time.time()
            return dict(_cached_weights)

        dynamic: dict[str, float] = {}
        for agent in agents:
            static_w = WEIGHTS[agent]
            if accuracy[agent] is not None:
                # accuracy[agent] is already an absolute 0..1 score — blend
                # it directly. Normalizing it as a *fraction of the sum of
                # all agents' accuracies* (as this used to) shrinks the
                # denominator right along with a bad agent's own score: a
                # lone agent correct only 10% of the time got acc_norm =
                # 0.1/0.1 = 1.0 — identical to a lone agent that's *always*
                # correct. The final normalization below still rescales
                # everything to sum to 1 across agents.
                dynamic[agent] = 0.7 * static_w + 0.3 * accuracy[agent]
            else:
                dynamic[agent] = static_w

        total = sum(dynamic.values())
        if total > 0:
            dynamic = {a: v / total for a, v in dynamic.items()}

        _cached_weights = dynamic
        _weights_computed_at = time.time()
        return dict(_cached_weights)


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _build_vote(
    agent_name: str,
    action: str,
    symbol: str,
    confidence: float,
    allocation_pct: float = 0,
    reasoning: str = "",
    extra: dict | None = None,
) -> dict:
    """Build a standardized vote dict for any specialist agent."""
    vote = {
        "agent": agent_name,
        "action": action,
        "symbol": symbol,
        "confidence": confidence,
        "allocation_pct": allocation_pct,
        "reasoning": reasoning,
    }
    if extra:
        vote.update(extra)
    return vote


def _record_source() -> str:
    """Return the ``agent_memory.source`` label aligned on the runtime mode.

    Keeps ``agent_memory.source`` in sync with ``trades.source`` so cross-
    table queries (e.g. accuracy filtered by mode) stay coherent
    (Review v5 Finding 3.3).
    """
    mode = get_runtime_mode()  # 'live' | 'paper' | 'sim'
    return "simulation" if mode == "sim" else mode


def _record_vote(
    agent_name: str,
    symbol: str,
    action: str,
    confidence: float,
    source: str,
) -> None:
    """Record a specialist vote in ``agent_memory``.

    ``trace_id`` is captured from the current cycle so
    ``evaluate_pending_trades`` can later resolve ``was_correct`` against
    the matching trade. Without it, the UPDATE matches zero rows and
    accuracy stays NULL forever (Review v5 Finding 3.2).
    """
    ok = _db_write(
        "INSERT INTO agent_memory "
        "(timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source,trace_id) "
        "VALUES (?,?,?,?,?,NULL,NULL,?,?)",
        (
            _ts(),
            agent_name,
            symbol,
            action,
            float(confidence),
            source,
            _get_trace_id(),
        ),
    )
    if not ok:
        logger.warning(
            "vote not persisted (agent_memory gap → skews dynamic weights): %s %s %s",
            agent_name,
            action,
            symbol,
        )


# ── Specialist node scaffolding ───────────────────────────────────────────────
#
# The specialist nodes share this LLM + JSON + Pydantic scaffolding.
# identical plumbing: read recent lessons, append them to the system prompt,
# call the LLM, parse+validate the JSON, then record the vote and return the
# accumulator dict. The *prompts* and *signal building* genuinely differ per
# agent, so those stay inline in each node; only the boilerplate is factored
# out here to remove ~4× duplication and keep the ``_no_llm_mode()`` gate and
# vote-recording in one place.


def _recent_lessons(agent_name: str, limit: int = 5) -> list[str]:
    """Most recent non-null lessons logged for ``agent_name`` (newest first)."""
    rows = _db_read(
        "SELECT lesson FROM agent_memory WHERE agent_name=? AND lesson IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT ?",
        (agent_name, limit),
    )
    return [r[0] for r in rows if r[0]]


def _with_lessons(system_prompt: str, lessons: list[str]) -> str:
    """Append a ``Tes erreurs récentes`` block to a system prompt if any."""
    if lessons:
        system_prompt += "\nTes erreurs récentes :\n" + "\n".join(
            f"  • {lesson}" for lesson in lessons
        )
    return system_prompt


def _untrusted(source: str, text: str) -> str:
    """Delimit externally-sourced text (news, web_search) for a prompt.

    Mitigates prompt injection: a news headline or web page could contain
    text crafted to look like an instruction. Wrapping it in explicit tags
    lets the system prompt (UNTRUSTED_DATA_NOTICE) tell the model to treat
    anything inside as data to analyze, never as instructions to follow.
    """
    return f'<untrusted_external_data source="{source}">\n{text}\n</untrusted_external_data>'


def _invoke_specialist(
    model,
    model_id: str,
    user: str,
    system: str,
    max_tokens: int,
    validator,
    display_name: str,
    web_search: bool = False,
) -> dict:
    """Run the LLM call + JSON parse + Pydantic validation for a specialist.

    Returns a validated vote dict with ``agent_name`` set. Falls back to the
    validator's safe defaults (``validator({})``) when the model returns
    unparseable output.
    """
    text = _llm(
        model,
        model_id,
        [{"role": "user", "content": user}],
        system=system,
        max_tokens=max_tokens,
        web_search=web_search,
    )
    raw = _parse_json_obj(text)
    vote = validator(raw) if raw else validator({})
    vote["agent_name"] = display_name
    return vote


def _emit_vote(name: str, vote_key: str, vote: dict, logs: list) -> dict:
    """Record the vote in ``agent_memory`` and build the node accumulator dict."""
    _record_vote(
        name,
        vote.get("symbol", ""),
        vote.get("action", "HOLD"),
        vote.get("confidence", 0.5),
        _record_source(),
    )
    return {"agent_votes": [vote], vote_key: vote, "log": logs}


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def sim_technician(state: MultiAgentState) -> dict:
    prices = state["prices"]
    pos = state["positions"]
    wl = get_watchlist()
    logs = [_entry("[SIM][TECH] RSI-based technical analysis")]

    rsi_map = {
        sym: _rsi(_sim_price_history.get(sym, [prices.get(sym, 100.0)]))
        for sym in wl
        if sym in prices
    }

    oversold = {s: r for s, r in rsi_map.items() if r < 35}
    overbought = {s: r for s, r in rsi_map.items() if r > 65 and s in pos}

    if overbought:
        # Sell the MOST overbought holding (highest RSI = strongest reversal
        # signal) — previously used min(), copy-pasted from the oversold/BUY
        # branch below where the lowest RSI is the strongest signal, which
        # picked the position barely past the threshold instead (Review
        # Finding).
        sym = max(overbought, key=overbought.get)
        action, conf, alloc = "SELL", 0.74, 0
        rsi_v = rsi_map[sym]
        reason = f"RSI={rsi_v:.1f} overbought — technical reversal signal"
        macd, bb, trend = "bearish", "upper", "down"
    elif oversold and len(pos) < MAX_POSITIONS:
        sym = min(oversold, key=oversold.get)
        action, conf, alloc = "BUY", 0.79, random.randint(15, MAX_ALLOC_PCT)
        rsi_v = rsi_map[sym]
        reason = f"RSI={rsi_v:.1f} oversold — technical bounce setup"
        macd, bb, trend = "bullish", "lower", "up"
    else:
        sym = wl[0] if wl else ""
        action, conf, alloc = "HOLD", 0.58, 0
        rsi_v = rsi_map.get(sym, 50.0)
        reason = f"RSI={rsi_v:.1f} — neutral zone, no setup"
        macd, bb, trend = "neutral", "mid", "sideways"

    vote = _build_vote(
        "technician",
        action,
        sym,
        conf,
        alloc,
        reason,
        extra={
            "agent_name": "Technician",
            "signals": [
                f"RSI({rsi_v:.1f}): {'oversold' if rsi_v < 35 else 'overbought' if rsi_v > 65 else 'neutral'}",
                f"MACD: {macd}",
                f"Bollinger Band: {bb}",
                f"Trend: {trend}",
            ],
            "key_indicators": {"rsi": round(rsi_v, 1), "macd": macd, "bb": bb, "trend": trend},
        },
    )
    logs.append(_entry(f"[SIM][TECH] {action} {sym} conf={conf:.0%} RSI={rsi_v:.1f}"))
    _record_vote("technician", sym, action, conf, _record_source())
    return {"agent_votes": [vote], "tech_vote": vote, "log": logs}


def sim_analyst(state: MultiAgentState) -> dict:
    prices = state["prices"]
    pos = state["positions"]
    sentiment = state.get("sentiment", {})
    wl = get_watchlist()
    logs = [_entry("[SIM][ANLST] sentiment-based fundamental analysis")]

    avg_sent = sum(sentiment.values()) / max(len(sentiment), 1)

    if avg_sent > 0.15 and len(pos) < MAX_POSITIONS:
        candidates = [s for s in wl if s not in pos and s in prices]
        sym = random.choice(candidates) if candidates else (wl[0] if wl else "")
        action = "BUY"
        conf = min(0.65 + abs(avg_sent) * 0.2, 0.85)
        alloc = random.randint(10, 30)
        reason = f"Positive sentiment ({avg_sent:+.2f}) — bullish catalyst detected"
        catalysts = ["[SIM] momentum surge", "[SIM] positive earnings sentiment"]
    elif avg_sent < -0.15 and pos:
        sym = min(pos.keys(), key=lambda s: sentiment.get(s, 0))
        action = "SELL"
        conf = min(0.65 + abs(avg_sent) * 0.2, 0.85)
        alloc = 0
        reason = f"Negative sentiment ({avg_sent:+.2f}) — bearish pressure building"
        catalysts = ["[SIM] negative news flow", "[SIM] sentiment deterioration"]
    else:
        sym = wl[0] if wl else ""
        action = "HOLD"
        conf = 0.55
        alloc = 0
        reason = f"Mixed sentiment ({avg_sent:+.2f}) — no clear fundamental catalyst"
        catalysts = []

    vote = _build_vote(
        "analyst",
        action,
        sym,
        conf,
        alloc,
        reason,
        extra={
            "agent_name": "Analyst",
            "signals": [
                f"Aggregate sentiment: {avg_sent:+.2f}",
                f"Market bias: {'bullish' if avg_sent > 0.15 else 'bearish' if avg_sent < -0.15 else 'neutral'}",
            ]
            + catalysts,
            "catalysts": catalysts,
            "sentiment_score": round(avg_sent, 2),
        },
    )
    logs.append(_entry(f"[SIM][ANLST] {action} {sym} conf={conf:.0%} sent={avg_sent:+.2f}"))
    _record_vote("analyst", sym, action, conf, _record_source())
    return {"agent_votes": [vote], "analyst_vote": vote, "log": logs}


def sim_risk_manager(state: MultiAgentState) -> dict:
    balance = state["balance"]
    pv = _portfolio_value(state)
    logs = [_entry("[SIM][RISK] calculating risk metrics")]

    exposure = (pv - balance) / pv if pv > 0 else 0.0
    danger_ratio = pv / INITIAL_BALANCE
    var_1d = pv * 0.02

    if danger_ratio < 0.7:
        risk_score, sizing, max_alloc = 9, "SKIP", 0
        warnings = ["DANGER ZONE — capital below 70% — no new positions"]
    elif danger_ratio < 0.85:
        risk_score, sizing, max_alloc = 7, "QUARTER", MAX_ALLOC_PCT // 4
        warnings = ["Capital preservation mode — reduced sizing"]
    elif exposure > 0.8:
        risk_score, sizing, max_alloc = 6, "HALF", MAX_ALLOC_PCT // 2
        warnings = ["High exposure — limit new positions"]
    else:
        risk_score, sizing, max_alloc = (
            max(2, round((1 - danger_ratio) * 10)),
            "FULL",
            MAX_ALLOC_PCT,
        )
        warnings = []

    reason = f"Risk {risk_score}/10 — {sizing} sizing. Exposure {exposure:.0%}. VaR(95%,1d) ~${var_1d:.0f}."

    vote = _build_vote(
        "risk_manager",
        "HOLD",
        "",
        0.5,
        max_alloc,
        reason,
        extra={
            "agent_name": "Risk Manager",
            "risk_score": risk_score,
            "max_safe_allocation_pct": float(max_alloc),
            "var_1d": round(var_1d, 2),
            "portfolio_exposure_after": round(exposure * 100, 1),
            "sizing_recommendation": sizing,
            "signals": [
                f"Risk score: {risk_score}/10",
                f"Portfolio danger ratio: {danger_ratio:.2f} (death at {DEATH_THRESHOLD/INITIAL_BALANCE:.2f})",
                f"Exposure: {exposure:.0%}",
                f"VaR 95% 1d: ${var_1d:.0f}",
                f"Sizing: {sizing}",
            ]
            + warnings,
            "warnings": warnings,
        },
    )
    logs.append(_entry(f"[SIM][RISK] score={risk_score}/10 sizing={sizing} VaR=${var_1d:.0f}"))
    _record_vote("risk_manager", "", "HOLD", 0.5, _record_source())
    return {"agent_votes": [vote], "risk_vote": vote, "log": logs}


def sim_macro_watcher(state: MultiAgentState) -> dict:
    sentiment = state.get("sentiment", {})
    pv = _portfolio_value(state)
    logs = [_entry("[SIM][MACRO] market regime analysis")]

    avg_sent = sum(sentiment.values()) / max(len(sentiment), 1)

    if pv < INITIAL_BALANCE * 0.7:
        regime, bias, exposure, macro_score = "risk-off", "bearish", 20, -0.8
        rotation = "defensive"
    elif pv > INITIAL_BALANCE * 1.3:
        regime, bias, exposure, macro_score = "risk-on", "bullish", 80, 0.7
        rotation = "tech"
    elif avg_sent > 0.15:
        regime, bias, exposure, macro_score = "risk-on", "bullish", 60, 0.4
        rotation = "growth"
    elif avg_sent < -0.15:
        regime, bias, exposure, macro_score = "risk-off", "bearish", 30, -0.4
        rotation = "defensive"
    else:
        regime, bias, exposure, macro_score = "transitional", "neutral", 50, 0.0
        rotation = "balanced"

    reason = f"Regime: {regime}. Portfolio health {pv/INITIAL_BALANCE:.0%}. Bias: {bias}."

    vote = _build_vote(
        "macro_watcher",
        "HOLD",
        "",
        0.5,
        0,
        reason,
        extra={
            "agent_name": "Macro Watcher",
            "market_regime": regime,
            "macro_bias": bias,
            "recommended_exposure": exposure,
            "sector_rotation": rotation,
            "signals": [
                f"Market regime: {regime}",
                f"Macro bias: {bias}",
                f"Portfolio health: {pv/INITIAL_BALANCE:.0%} of initial capital",
                f"Aggregate sentiment: {avg_sent:+.2f}",
                f"Recommended exposure: {exposure}%",
                f"Sector rotation: {rotation}",
            ],
            "macro_score": round(macro_score, 2),
        },
    )
    logs.append(_entry(f"[SIM][MACRO] {regime} {bias} exposure={exposure}%"))
    _record_vote("macro_watcher", "", "HOLD", 0.5, _record_source())
    return {"agent_votes": [vote], "macro_vote": vote, "log": logs}


def sim_economist(state: MultiAgentState) -> dict:
    pv = _portfolio_value(state)
    logs = [_entry("[SIM][ECON] economic cycle analysis")]

    health = pv / INITIAL_BALANCE
    if health < 0.7:
        regime, trajectory, curve, inflation, score = (
            "recession",
            "cutting",
            "inverted",
            "low",
            -0.7,
        )
    elif health > 1.3:
        regime, trajectory, curve, inflation, score = (
            "expansion",
            "hiking",
            "normal",
            "moderate",
            0.5,
        )
    else:
        regime, trajectory, curve, inflation, score = (
            "transitional",
            "pausing",
            "flat",
            "moderate",
            0.0,
        )

    reason = f"[SIM] Régime: {regime}. Trajectoire taux: {trajectory}. Score éco: {score:+.1f}."
    vote = _build_vote(
        "economist",
        "HOLD",
        "",
        0.5,
        0,
        reason,
        extra={
            "agent_name": "Economist",
            "economic_regime": regime,
            "rate_trajectory": trajectory,
            "yield_curve": curve,
            "inflation_regime": inflation,
            "economic_score": round(score, 2),
            "signals": [
                f"Economic regime: {regime}",
                f"Rate trajectory: {trajectory}",
                f"Yield curve: {curve}",
                f"Inflation regime: {inflation}",
                f"Economic score: {score:+.1f}",
            ],
        },
    )
    logs.append(_entry(f"[SIM][ECON] {regime} rate={trajectory} score={score:+.1f}"))
    _record_vote("economist", "", "HOLD", 0.5, _record_source())
    return {"agent_votes": [vote], "economist_vote": vote, "log": logs}


def sim_geopolitician(state: MultiAgentState) -> dict:
    sentiment = state.get("sentiment", {})
    logs = [_entry("[SIM][GEO] geopolitical risk assessment")]

    avg_sent = sum(sentiment.values()) / max(len(sentiment), 1)
    if avg_sent < -0.3:
        risk, regions, sectors, bias, score = 7, ["Global"], ["energy", "defense"], "cautious", -0.5
    elif avg_sent > 0.3:
        risk, regions, sectors, bias, score = 2, [], [], "favorable", 0.2
    else:
        risk, regions, sectors, bias, score = 4, ["Middle East"], ["energy"], "neutral", -0.1

    reason = f"[SIM] Risque géopolitique {risk}/10. Biais: {bias}. Score: {score:+.1f}."
    vote = _build_vote(
        "geopolitician",
        "HOLD",
        "",
        0.5,
        0,
        reason,
        extra={
            "agent_name": "Geopolitician",
            "geopolitical_risk": risk,
            "risk_regions": regions,
            "affected_sectors": sectors,
            "geo_bias": bias,
            "geo_score": round(score, 2),
            "signals": [
                f"Geopolitical risk: {risk}/10",
                f"Risk regions: {regions or ['Aucune tension majeure']}",
                f"Affected sectors: {sectors or ['N/A']}",
                f"Geopolitical bias: {bias}",
            ],
        },
    )
    logs.append(_entry(f"[SIM][GEO] risk={risk}/10 bias={bias} score={score:+.1f}"))
    _record_vote("geopolitician", "", "HOLD", 0.5, _record_source())
    return {"agent_votes": [vote], "geo_vote": vote, "log": logs}


# ═══════════════════════════════════════════════════════════════════════════════
# SUPERVISOR NODE
# ═══════════════════════════════════════════════════════════════════════════════


def supervisor_node(state: MultiAgentState) -> dict:
    logs = [_entry("supervisor: preparing context brief for team")]

    if _no_llm_mode():
        pv = _portfolio_value(state)
        mode = (
            "PANIC"
            if pv < INITIAL_BALANCE * 0.7
            else ("GREED" if pv > INITIAL_BALANCE * 1.5 else "NORMAL")
        )
        brief = (
            f"[SIM] 1. Portfolio ${pv:.0f} ({pv/INITIAL_BALANCE:.0%}). Mode: {mode}. "
            f"2. {len(state['positions'])} open positions / {MAX_POSITIONS} max. "
            f"3. Market data available for {len(state['prices'])} symbols."
        )
        logs.append(_entry(f"[SIM] supervisor: brief ready — {mode} mode"))
        return {"supervisor_brief": brief, "log": logs}

    pv = _portfolio_value(state)
    mode = (
        "PANIC"
        if pv < INITIAL_BALANCE * 0.5
        else ("GREED" if pv > INITIAL_BALANCE * 1.5 else "NORMAL")
    )

    prompt = (
        f"CYCLE #{state['round']} | MODE: {mode}\n"
        f"Portfolio: ${pv:.2f} | Cash: ${state['balance']:.2f} | "
        f"Positions: {len(state['positions'])}/{MAX_POSITIONS}\n"
        f"Prices: {json.dumps({s: f'${p:.2f}' for s, p in state['prices'].items()})}\n"
        f"News snippet:\n{_untrusted('news', (state.get('news') or 'N/A')[:200])}\n\n"
        "Résume en 3 points clés ce contexte de marché pour briefer ton équipe de traders. "
        "Sois factuel et concis (max 60 mots)."
    )
    brief = _llm(
        haiku,
        HAIKU_ID,
        [{"role": "user", "content": prompt}],
        system=UNTRUSTED_DATA_NOTICE,
        max_tokens=120,
    )
    logs.append(_entry(f"supervisor: brief ready ({len(brief)} chars)"))
    return {"supervisor_brief": brief, "log": logs}


def _route_to_agents(state: MultiAgentState) -> list:
    """Fan-out via Send to 6 parallel agents.

    LangGraph exécute les 6 nœuds en parallèle dans des threads séparés.
    Chaque agent reçoit une copie du state complet et produit un vote indépendant.
    Les 6 votes convergent ensuite vers ``arbitrate_node`` (fan-in implicite de LangGraph).
    """
    base = dict(state)
    return [
        Send("technician", {**base, "agent_role": "technician"}),
        Send("analyst", {**base, "agent_role": "analyst"}),
        Send("risk_manager", {**base, "agent_role": "risk_manager"}),
        Send("macro_watcher", {**base, "agent_role": "macro_watcher"}),
        Send("economist", {**base, "agent_role": "economist"}),
        Send("geopolitician", {**base, "agent_role": "geopolitician"}),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# PARALLEL AGENT NODES
# ═══════════════════════════════════════════════════════════════════════════════


def technician_node(state: MultiAgentState) -> dict:
    # Analyse purement chartiste : RSI(14) sur _live_price_history, MACD, Bollinger.
    # Vote BUY si RSI < 35 (survente), SELL si RSI > 65 + position ouverte (surachat).
    # Modèle : Haiku (rapide, pas de web search — données techniques suffisent).
    if _no_llm_mode():
        return sim_technician(state)

    prices = state["prices"]
    pos = state["positions"]
    wl = get_watchlist()
    logs = [_entry("technician: technical analysis")]

    recent_lessons = _recent_lessons("technician")

    rsi_map = {
        sym: _rsi(_live_price_history.get(sym, [prices.get(sym, 100.0)]))
        for sym in wl
        if sym in prices
    }
    positions_display = {
        sym: {
            "shares": round(p["shares"], 4),
            "avg_price": round(p.get("avg_price", 0), 2),
            "now": round(prices.get(sym, 0), 2),
            "pnl%": round(((prices.get(sym, 1) / max(p.get("avg_price", 1), 0.01)) - 1) * 100, 2),
        }
        for sym, p in pos.items()
    }

    system = _with_lessons(TECHNICIAN_SYSTEM_PROMPT, recent_lessons)
    user = (
        f"TECHNICAL ANALYSIS — Cycle #{state['round']}\n\n"
        f"PRIX ACTUELS:\n{json.dumps({s: f'${p:.2f}' for s, p in prices.items()}, indent=2)}\n\n"
        f"RSI(14) par symbole:\n{json.dumps({s: round(r, 1) for s, r in rsi_map.items()}, indent=2)}\n\n"
        f"POSITIONS ACTUELLES:\n{json.dumps(positions_display, indent=2)}\n\n"
        f"WATCHLIST: {wl}\n"
        f"POSITIONS MAX: {MAX_POSITIONS} | ACTUELLES: {len(pos)}\n\n"
        "Retourne ce JSON uniquement :\n"
        '{\n  "agent": "technician",\n  "action": "BUY|SELL|HOLD",\n'
        '  "symbol": "TICKER",\n  "confidence": 0.0,\n  "allocation_pct": 10,\n'
        '  "reasoning": "2 phrases",\n'
        '  "key_indicators": {"rsi": 0.0, "macd": "bullish|bearish|neutral", '
        '"bb": "lower|mid|upper", "trend": "up|down|sideways"}\n}'
    )

    vote = _invoke_specialist(haiku, HAIKU_ID, user, system, 512, validate_tech_vote, "Technician")
    ki = vote.get("key_indicators", {})
    rsi_val = ki.get("rsi") or rsi_map.get(vote.get("symbol", ""), 50.0)
    vote["signals"] = [
        f"RSI({rsi_val:.1f}): {'oversold' if rsi_val < 35 else 'overbought' if rsi_val > 65 else 'neutral'}",
        f"MACD: {ki.get('macd', 'N/A')}",
        f"Bollinger Band: {ki.get('bb', 'N/A')}",
        f"Trend: {ki.get('trend', 'N/A')}",
    ]
    logs.append(
        _entry(
            f"technician: {vote.get('action')} {vote.get('symbol','')} conf={vote.get('confidence',0):.0%}"
        )
    )
    return _emit_vote("technician", "tech_vote", vote, logs)


def analyst_node(state: MultiAgentState) -> dict:
    # Analyse fondamentale + sentiment : news récentes, score Twitter (-1 → +1), catalyseurs.
    # Seul agent avec web_search=True → peut chercher des infos en temps réel via Claude.
    # Modèle : Sonnet (raisonnement plus profond nécessaire pour interpréter les actualités).
    if _no_llm_mode():
        return sim_analyst(state)

    pos = state["positions"]
    sentiment = state.get("sentiment", {})
    wl = get_watchlist()
    logs = [_entry("analyst: fundamental + sentiment analysis")]

    recent_lessons = _recent_lessons("analyst")

    system = _with_lessons(ANALYST_SYSTEM_PROMPT, recent_lessons)
    user = (
        f"FUNDAMENTAL ANALYSIS — Cycle #{state['round']}\n\n"
        f"NEWS RÉCENTES:\n{_untrusted('news', (state.get('news') or 'Aucune news')[:600])}\n\n"
        f"SENTIMENT TWITTER (-1=baissier → +1=haussier):\n"
        f"{json.dumps(sentiment, indent=2)}\n\n"
        f"POSITIONS ACTUELLES: {list(pos.keys())}\n"
        f"WATCHLIST: {wl} | POSITIONS MAX: {MAX_POSITIONS}\n\n"
        f"BRIEF SUPERVISEUR:\n{state.get('supervisor_brief', '')}\n\n"
        "Retourne ce JSON uniquement :\n"
        '{\n  "agent": "analyst",\n  "action": "BUY|SELL|HOLD",\n'
        '  "symbol": "TICKER",\n  "confidence": 0.0,\n  "allocation_pct": 10,\n'
        '  "reasoning": "2 phrases",\n  "catalysts": ["catalyst1"],\n'
        '  "sentiment_score": 0.0\n}'
    )

    vote = _invoke_specialist(
        sonnet,
        SONNET_ID,
        user,
        system,
        512,
        validate_analyst_vote,
        "Analyst",
        web_search=True,
    )
    sent_score = vote.get("sentiment_score", 0.0)
    catalysts_list = vote.get("catalysts", [])
    vote["signals"] = [
        f"Sentiment score: {sent_score:+.2f}",
        f"Market bias: {'bullish' if sent_score > 0.15 else 'bearish' if sent_score < -0.15 else 'neutral'}",
    ] + catalysts_list
    logs.append(
        _entry(
            f"analyst: {vote.get('action')} {vote.get('symbol','')} conf={vote.get('confidence',0):.0%}"
        )
    )
    return _emit_vote("analyst", "analyst_vote", vote, logs)


def risk_manager_node(state: MultiAgentState) -> dict:
    # Ne vote PAS sur la direction — fournit un score de risque (0-10) et un sizing
    # (FULL / HALF / QUARTER / SKIP). Un risk_score > 8 veto le BUY dans arbitrate_node.
    # Calcule Kelly depuis les vrais postmortems (≥ 5 trades clôturés), sinon priors conservateurs.
    if _no_llm_mode():
        return sim_risk_manager(state)

    pos = state["positions"]
    balance = state["balance"]
    pv = _portfolio_value(state)
    logs = [_entry("risk_manager: risk metrics calculation")]

    recent_lessons = _recent_lessons("risk_manager")

    exposure = (pv - balance) / pv if pv > 0 else 0.0
    danger_ratio = pv / INITIAL_BALANCE
    risk_metrics = state.get("risk_metrics") or {}
    var_1d = pv * 0.025

    # Kelly from actual closed-trade outcomes (postmortem.pnl_pct, stored in %).
    # Falls back to conservative priors below 5 closed trades.
    pnl_rows = _db_read(
        "SELECT pnl_pct FROM postmortem WHERE pnl_pct IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT 20"
    )
    pnl_fracs = [float(r[0]) / 100.0 for r in pnl_rows]
    kelly_source = "réel (postmortem)"
    if len(pnl_fracs) >= 5:
        win_rate_est, avg_win_est, avg_loss_est = win_stats(pnl_fracs)
    else:
        win_rate_est, avg_win_est, avg_loss_est = 0.55, 0.08, 0.05
        kelly_source = "estimé (< 5 trades clôturés)"
    kelly_f = kelly_fraction(win_rate_est, avg_win_est, avg_loss_est)
    kelly_alloc = max(0, min(kelly_f * 100, MAX_ALLOC_PCT))

    system = _with_lessons(RISK_MANAGER_SYSTEM_PROMPT, recent_lessons)
    user = (
        f"RISK ASSESSMENT — Cycle #{state['round']}\n\n"
        f"MÉTRIQUES CALCULÉES (Python pur) :\n"
        f"  Portfolio value:    ${pv:.2f}\n"
        f"  Cash:               ${balance:.2f}\n"
        f"  Exposure:           {exposure:.1%}\n"
        f"  Danger ratio:       {danger_ratio:.2f} (mort si < {DEATH_THRESHOLD/INITIAL_BALANCE:.2f})\n"
        f"  VaR 95% 1j:        ${var_1d:.2f}\n"
        f"  Kelly allocation:   {kelly_alloc:.1f}% — {kelly_source} "
        f"(win rate {win_rate_est:.0%}, avg win {avg_win_est:.1%}, avg loss {avg_loss_est:.1%})\n"
        f"  Sharpe (indicatif): {risk_metrics.get('sharpe', 0.0):.2f}\n"
        f"  Max drawdown:       {risk_metrics.get('max_drawdown_pct', 0.0):.1f}%\n"
        f"  Drawdown courant:   {risk_metrics.get('current_drawdown_pct', 0.0):.1f}%\n"
        f"  Positions:          {len(pos)}/{MAX_POSITIONS}\n\n"
        f"BRIEF SUPERVISEUR: {state.get('supervisor_brief', '')[:200]}\n\n"
        "Retourne ce JSON uniquement :\n"
        '{\n  "agent": "risk_manager",\n  "risk_score": 5,\n'
        '  "max_safe_allocation_pct": 20.0,\n  "var_1d": 25.0,\n'
        '  "portfolio_exposure_after": 40.0,\n'
        '  "sizing_recommendation": "FULL|HALF|QUARTER|SKIP",\n'
        '  "reasoning": "2 phrases",\n  "warnings": []\n}'
    )

    vote = _invoke_specialist(
        haiku, HAIKU_ID, user, system, 400, validate_risk_vote, "Risk Manager"
    )
    vote.setdefault("action", "HOLD")
    vote.setdefault("symbol", "")
    vote.setdefault("confidence", 0.5)
    vote.setdefault("allocation_pct", vote.get("max_safe_allocation_pct", MAX_ALLOC_PCT))
    vote["signals"] = [
        f"Risk score: {vote.get('risk_score', 5)}/10",
        f"Danger ratio: {danger_ratio:.2f} (death at {DEATH_THRESHOLD/INITIAL_BALANCE:.2f})",
        f"Exposure: {exposure:.0%}",
        f"VaR 95% 1d: ${var_1d:.2f}",
        f"Kelly allocation: {kelly_alloc:.1f}% ({kelly_source})",
        f"Sharpe: {risk_metrics.get('sharpe', 0.0):.2f} | "
        f"DD: {risk_metrics.get('current_drawdown_pct', 0.0):.1f}% "
        f"(max {risk_metrics.get('max_drawdown_pct', 0.0):.1f}%)",
        f"Sizing: {vote.get('sizing_recommendation', 'N/A')}",
    ] + vote.get("warnings", [])

    logs.append(
        _entry(
            f"risk_manager: score={vote.get('risk_score',5)}/10 "
            f"sizing={vote.get('sizing_recommendation','?')} "
            f"VaR=${vote.get('var_1d',0):.0f}"
        )
    )
    return _emit_vote("risk_manager", "risk_vote", vote, logs)


def macro_watcher_node(state: MultiAgentState) -> dict:
    # Détermine le régime de marché global (risk-on / risk-off / transitional).
    # Consomme les données FRED (taux FED, 10Y) + CNN Fear & Greed Index + sentiment agrégé.
    # Un régime risk-off réduit de 50 % le score BUY composite dans arbitrate_node.
    if _no_llm_mode():
        return sim_macro_watcher(state)

    sentiment = state.get("sentiment", {})
    pv = _portfolio_value(state)
    pos = state["positions"]
    logs = [_entry("macro_watcher: regime analysis")]

    recent_lessons = _recent_lessons("macro_watcher")

    avg_sent = sum(sentiment.values()) / max(len(sentiment), 1)

    system = _with_lessons(MACRO_WATCHER_SYSTEM_PROMPT, recent_lessons)
    fear_greed = state.get("fear_greed")
    # FRED data moved to economist_node — macro_watcher focuses on short-term sentiment only.
    system += (
        f"\n\nFear & Greed Index : {json.dumps(fear_greed, default=str) if fear_greed else 'N/A'}."
    )
    user = (
        f"MARKET SENTIMENT ANALYSIS — Cycle #{state['round']}\n\n"
        f"SENTIMENT AGRÉGÉ: {avg_sent:+.2f} (-1=très baissier, +1=très haussier)\n"
        f"SENTIMENT PAR SYMBOLE: {json.dumps(sentiment, indent=2)}\n"
        f"DIVERSIFICATION: {len(pos)}/{MAX_POSITIONS} positions\n\n"
        f"BRIEF SUPERVISEUR: {state.get('supervisor_brief', '')[:200]}\n\n"
        "Retourne ce JSON uniquement :\n"
        '{\n  "agent": "macro_watcher",\n'
        '  "market_regime": "risk-on|risk-off|transitional",\n'
        '  "macro_bias": "bullish|bearish|neutral",\n'
        '  "recommended_exposure": 50,\n'
        '  "sector_rotation": "description courte",\n'
        '  "reasoning": "2 phrases",\n'
        '  "macro_score": 0.0\n}'
    )

    vote = _invoke_specialist(
        haiku, HAIKU_ID, user, system, 400, validate_macro_vote, "Macro Watcher"
    )
    vote.setdefault("action", "HOLD")
    vote.setdefault("symbol", "")
    vote.setdefault("confidence", 0.5)
    vote.setdefault("allocation_pct", 0)
    vote["signals"] = [
        f"Market regime: {vote.get('market_regime', 'N/A')}",
        f"Macro bias: {vote.get('macro_bias', 'N/A')}",
        f"Portfolio health: {pv/INITIAL_BALANCE:.0%} of initial capital",
        f"Aggregate sentiment: {avg_sent:+.2f}",
        f"Recommended exposure: {vote.get('recommended_exposure', 'N/A')}%",
        f"Sector rotation: {vote.get('sector_rotation', 'N/A')}",
    ]

    logs.append(
        _entry(
            f"macro_watcher: {vote.get('market_regime','?')} {vote.get('macro_bias','?')} "
            f"score={vote.get('macro_score',0):+.2f}"
        )
    )
    return _emit_vote("macro_watcher", "macro_vote", vote, logs)


def economist_node(state: MultiAgentState) -> dict:
    # Analyse le cycle économique long : courbe des taux, trajectoire Fed, inflation, PMI.
    # Fournit un economic_score (-1 → +1) qui peut freiner les BUY en contexte récessif.
    # Modèle : Haiku (données FRED structurées fournies — pas de web search nécessaire).
    # Cache 1 h (SLOW_AGENT_TTL_SEC) : les données FRED changent au mieux quotidiennement.
    if _no_llm_mode():
        return sim_economist(state)

    cached = _get_cached_vote("economist")
    if cached:
        logs = [
            _entry(
                f"economist: cached vote reused (TTL {_SLOW_AGENT_TTL_SEC}s) — "
                f"{cached.get('economic_regime','?')} score={cached.get('economic_score',0):+.2f}"
            )
        ]
        # Still record this cycle's use of the cached vote in agent_memory —
        # skipping _emit_vote() here meant a cache hit (the overwhelming
        # majority of cycles at a 15min TTL vs. a shorter agent interval) left
        # no agent_memory row at all, so was_correct/accuracy tracking and
        # dynamic-weight blending silently under-counted this agent's real
        # participation (Review Finding).
        return _emit_vote("economist", "economist_vote", cached, logs)

    pv = _portfolio_value(state)
    macro_indicators = state.get("macro_indicators") or {}
    logs = [_entry("economist: macro cycle analysis")]

    recent_lessons = _recent_lessons("economist")
    system = _with_lessons(ECONOMIST_SYSTEM_PROMPT, recent_lessons)
    user = (
        f"ECONOMIC CYCLE ANALYSIS — Cycle #{state['round']}\n\n"
        f"DONNÉES MACRO FRED :\n{json.dumps(macro_indicators, indent=2, default=str)}\n\n"
        f"PORTFOLIO HEALTH: ${pv:.2f} ({pv/INITIAL_BALANCE:.0%} du capital initial)\n\n"
        f"BRIEF SUPERVISEUR: {state.get('supervisor_brief', '')[:200]}\n\n"
        "Retourne ce JSON uniquement :\n"
        '{\n  "agent": "economist",\n'
        '  "economic_regime": "expansion|slowdown|recession|recovery|transitional",\n'
        '  "rate_trajectory": "hiking|pausing|cutting",\n'
        '  "yield_curve": "normal|flat|inverted",\n'
        '  "inflation_regime": "high|moderate|low",\n'
        '  "economic_score": 0.0,\n'
        '  "reasoning": "2 phrases"\n}'
    )

    vote = _invoke_specialist(
        haiku, HAIKU_ID, user, system, 400, validate_economist_vote, "Economist"
    )
    vote.setdefault("action", "HOLD")
    vote.setdefault("symbol", "")
    vote.setdefault("confidence", 0.5)
    vote.setdefault("allocation_pct", 0)
    vote["signals"] = [
        f"Economic regime: {vote.get('economic_regime', 'N/A')}",
        f"Rate trajectory: {vote.get('rate_trajectory', 'N/A')}",
        f"Yield curve: {vote.get('yield_curve', 'N/A')}",
        f"Inflation regime: {vote.get('inflation_regime', 'N/A')}",
        f"Economic score: {vote.get('economic_score', 0.0):+.2f}",
    ]
    logs.append(
        _entry(
            f"economist: {vote.get('economic_regime','?')} rate={vote.get('rate_trajectory','?')} "
            f"score={vote.get('economic_score',0):+.2f}"
        )
    )
    _set_cached_vote("economist", vote)
    return _emit_vote("economist", "economist_vote", vote, logs)


def geopolitician_node(state: MultiAgentState) -> dict:
    # Évalue les risques géopolitiques en temps réel (conflits, sanctions, élections).
    # web_search=True car les événements géopolitiques nécessitent des infos actuelles.
    # Un geo_risk > 7 dampène les BUY de 50 % dans arbitrate_node.
    # Modèle : Sonnet (interprétation nuancée des tensions internationales).
    # Cache 1 h (SLOW_AGENT_TTL_SEC) : les situations géo évoluent à l'heure, pas à la minute.
    if _no_llm_mode():
        return sim_geopolitician(state)

    cached = _get_cached_vote("geopolitician")
    if cached:
        logs = [
            _entry(
                f"geopolitician: cached vote reused (TTL {_SLOW_AGENT_TTL_SEC}s) — "
                f"risk={cached.get('geopolitical_risk',3)}/10 "
                f"score={cached.get('geo_score',0):+.2f}"
            )
        ]
        # See the matching comment in economist_node — a cache hit must still
        # record a fresh agent_memory row (Review Finding).
        return _emit_vote("geopolitician", "geo_vote", cached, logs)

    logs = [_entry("geopolitician: geopolitical risk assessment")]
    recent_lessons = _recent_lessons("geopolitician")
    system = _with_lessons(GEOPOLITICIAN_SYSTEM_PROMPT, recent_lessons)
    user = (
        f"GEOPOLITICAL RISK ASSESSMENT — Cycle #{state['round']}\n\n"
        f"NEWS RÉCENTES:\n{_untrusted('news', (state.get('news') or 'Aucune news')[:400])}\n\n"
        f"BRIEF SUPERVISEUR: {state.get('supervisor_brief', '')[:200]}\n\n"
        "Retourne ce JSON uniquement :\n"
        '{\n  "agent": "geopolitician",\n'
        '  "geopolitical_risk": 3,\n'
        '  "risk_regions": ["région1"],\n'
        '  "affected_sectors": ["secteur1"],\n'
        '  "geo_bias": "cautious|neutral|favorable",\n'
        '  "geo_score": 0.0,\n'
        '  "reasoning": "2 phrases"\n}'
    )

    vote = _invoke_specialist(
        sonnet, SONNET_ID, user, system, 400, validate_geo_vote, "Geopolitician", web_search=True
    )
    vote.setdefault("action", "HOLD")
    vote.setdefault("symbol", "")
    vote.setdefault("confidence", 0.5)
    vote.setdefault("allocation_pct", 0)
    vote["signals"] = [
        f"Geopolitical risk: {vote.get('geopolitical_risk', 3)}/10",
        f"Risk regions: {vote.get('risk_regions', []) or ['Aucune tension majeure']}",
        f"Affected sectors: {vote.get('affected_sectors', []) or ['N/A']}",
        f"Geopolitical bias: {vote.get('geo_bias', 'neutral')}",
        f"Geo score: {vote.get('geo_score', 0.0):+.2f}",
    ]
    logs.append(
        _entry(
            f"geopolitician: risk={vote.get('geopolitical_risk',3)}/10 "
            f"bias={vote.get('geo_bias','neutral')} "
            f"score={vote.get('geo_score',0):+.2f}"
        )
    )
    _set_cached_vote("geopolitician", vote)
    return _emit_vote("geopolitician", "geo_vote", vote, logs)


# ═══════════════════════════════════════════════════════════════════════════════
# ARBITRATION NODE
# ═══════════════════════════════════════════════════════════════════════════════


def arbitrate_node(state: MultiAgentState) -> dict:
    # ── PHASE 1 : agrégation des votes ────────────────────────────────────────
    # Chaque spécialiste a déposé un vote dans state["agent_votes"].
    # L'arbitre calcule un score composite pondéré pour chaque action possible,
    # puis applique des filtres déterministes avant de passer la main au LLM Sonnet
    # qui rédige la synthèse finale (reasoning, émotion, market_intel).
    votes = state.get("agent_votes", [])
    logs = [_entry(f"arbitrate: {len(votes)} votes received — computing decision")]

    vote_map = {v.get("agent", ""): v for v in votes}
    tech_v = vote_map.get("technician", {})
    ana_v = vote_map.get("analyst", {})
    risk_v = vote_map.get("risk_manager", {})
    macro_v = vote_map.get("macro_watcher", {})
    eco_v = vote_map.get("economist", {})
    geo_v = vote_map.get("geopolitician", {})

    # ── PHASE 2 : calcul du score composite ───────────────────────────────────
    # Formule : score(action) += poids_agent × confiance_agent
    # Seuls Technician et Analyst votent sur la direction ; Risk et Macro alimentent
    # un HOLD de base (ils freinent les décisions actives plutôt qu'ils n'en proposent).
    dynamic_weights = _compute_dynamic_weights()
    logs.append(_entry(f"arbitrate: weights_used={dynamic_weights}"))

    # Composite action scores (risk_manager & macro_watcher don't vote on direction)
    action_scores: dict[str, float] = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    for v in [tech_v, ana_v]:
        agent = v.get("agent", "")
        weight = dynamic_weights.get(agent, 0.0)
        action = v.get("action", "HOLD")
        conf = float(v.get("confidence", 0.5))
        action_scores[action] = action_scores.get(action, 0.0) + weight * conf

    # Apply HOLD weight for macro + risk + economist + geo as a baseline
    hold_weight = (
        dynamic_weights["risk_manager"] * 0.4
        + dynamic_weights["macro_watcher"] * 0.25
        + dynamic_weights.get("economist", 0.0) * 0.25
        + dynamic_weights.get("geopolitician", 0.0) * 0.1
    )
    action_scores["HOLD"] += hold_weight * 0.5

    # ── PHASE 3 : filtres déterministes (avant LLM) ───────────────────────────
    # Ces filtres s'appliquent même si le LLM n'est pas disponible.
    # Ils protègent le capital contre les conditions de marché extrêmes.

    # Risk veto: risk_score > 8 heavily penalises BUY
    risk_score = float(risk_v.get("risk_score", 5))
    if risk_score > 8:
        action_scores["BUY"] *= 0.15
        logs.append(
            _entry(f"arbitrate: RISK VETO — score={risk_score:.0f}/10 → BUY penalized", "warning")
        )

    # Macro filter: risk-off dampens BUY
    regime = macro_v.get("market_regime", "transitional")
    if regime == "risk-off":
        action_scores["BUY"] *= 0.5
        logs.append(_entry("arbitrate: MACRO FILTER — risk-off → BUY dampened", "warning"))

    # Economic headwind: negative economic cycle dampens BUY
    economic_score = float(eco_v.get("economic_score", 0.0))
    if economic_score < -0.5:
        action_scores["BUY"] *= 0.6
        logs.append(
            _entry(
                f"arbitrate: ECONOMIC HEADWIND — score={economic_score:.2f} → BUY dampened",
                "warning",
            )
        )

    # Geopolitical risk: high risk dampens BUY
    geo_risk = float(geo_v.get("geopolitical_risk", 3))
    if geo_risk > 7:
        action_scores["BUY"] *= 0.5
        logs.append(
            _entry(
                f"arbitrate: GEO RISK HIGH — risk={geo_risk:.0f}/10 → BUY dampened",
                "warning",
            )
        )

    final_action = max(action_scores, key=action_scores.get)
    composite_conf = action_scores[final_action]
    max_alloc = float(risk_v.get("max_safe_allocation_pct", MAX_ALLOC_PCT))

    # Symbol: highest-confidence directional voter for the winning action
    symbol, best_c = "", 0.0
    for v in [tech_v, ana_v]:
        if v.get("action") == final_action and float(v.get("confidence", 0)) > best_c:
            best_c = float(v.get("confidence", 0))
            symbol = v.get("symbol", "")

    dissenting = [
        v.get("agent", "")
        for v in [tech_v, ana_v]
        if v.get("action") != final_action and v.get("agent")
    ]
    consensus = (
        "strong" if composite_conf > 0.6 else ("moderate" if composite_conf > 0.4 else "weak")
    )

    # Portfolio-level correlation risk: damp BUY when the target is highly
    # correlated with an existing position (concentration risk without diversification).
    positions = state.get("positions") or {}
    if final_action == "BUY" and symbol and positions:
        buy_target = symbol  # for the log line below, even if the action flips
        max_corr = _portfolio_correlation(symbol, list(positions.keys()))
        if max_corr > 0.7:
            action_scores["BUY"] *= 0.75
            new_action = max(action_scores, key=action_scores.get)
            if new_action != final_action:
                # Damping can flip the winner to a different action — the BUY
                # target symbol is meaningless for that action. Re-derive it
                # the same way the original selection did (Review Finding:
                # a flip previously kept targeting the old BUY ticker).
                symbol, best_c = "", 0.0
                for v in [tech_v, ana_v]:
                    if v.get("action") == new_action and float(v.get("confidence", 0)) > best_c:
                        best_c = float(v.get("confidence", 0))
                        symbol = v.get("symbol", "")
            final_action = new_action
            composite_conf = action_scores[final_action]
            logs.append(
                _entry(
                    f"arbitrate: CORRELATION RISK — {buy_target} corr={max_corr:.2f} with "
                    f"open positions → BUY×0.75",
                    "warning",
                )
            )

    votes_summary = json.dumps(
        [{k: vv for k, vv in v.items() if k not in ("key_indicators",)} for v in votes],
        indent=2,
        default=str,
    )
    # analyst_node/geopolitician_node run with web_search=True — their
    # free-text fields (reasoning, catalysts, risk_regions, ...) can echo
    # content from a fetched web page, including a page crafted to look
    # like an instruction. Wrap the vote dump the same way raw news text is
    # wrapped elsewhere before splicing it into this second LLM call
    # (Review Finding — the news wrapping fix's remaining gap).
    votes_summary_untrusted = _untrusted("agent_votes", votes_summary)

    if _no_llm_mode():
        tag = "PAPER" if _paper_mode["enabled"] else "SIM"
        emotion = "FOCUSED" if composite_conf > 0.6 else "CALM"
        thoughts = (
            f"[{tag}] Composite: {final_action} {symbol}. "
            f"Score={composite_conf:.2f}. Consensus={consensus}."
        )
        market_intel = macro_v.get("reasoning", "")
        reasoning = (
            f"BUY={action_scores['BUY']:.2f} SELL={action_scores['SELL']:.2f} "
            f"HOLD={action_scores['HOLD']:.2f} | Risk {risk_score:.0f}/10 | {regime} | "
            f"Éco: {economic_score:+.1f} | Géo: {geo_risk:.0f}/10"
        )
    else:
        system_arb = ARBITRATE_SYSTEM_PROMPT
        user_arb = (
            f"ARBITRATION — Cycle #{state['round']}\n\n"
            f"VOTES:\n{votes_summary_untrusted}\n\n"
            f"SCORES COMPOSITES:\n"
            f"  BUY={action_scores['BUY']:.3f} | SELL={action_scores['SELL']:.3f} | HOLD={action_scores['HOLD']:.3f}\n\n"
            f"CONTEXTE SUPPLÉMENTAIRE:\n"
            f"  Cycle économique: {eco_v.get('economic_regime','?')} | Score éco: {economic_score:+.2f}\n"
            f"  Risque géopolitique: {geo_risk:.0f}/10 | Bias géo: {geo_v.get('geo_bias','neutral')} | Score: {float(geo_v.get('geo_score',0)):+.2f}\n\n"
            f"DÉCISION CALCULÉE: {final_action} {symbol} (conf={composite_conf:.2f})\n"
            f"Risk score: {risk_score:.0f}/10 | Régime: {regime} | Max alloc: {max_alloc:.0f}%\n"
            f"Agents dissidents: {dissenting}\n\n"
            f"Retourne ce JSON uniquement :\n"
            f'{{\n  "action": "BUY|SELL|HOLD",\n  "symbol": "TICKER",\n'
            f'  "allocation_pct": {min(max_alloc, MAX_ALLOC_PCT):.0f},\n'
            f'  "confidence": {composite_conf:.2f},\n'
            f'  "reasoning": "synthèse 2-3 phrases",\n'
            f'  "dissenting_agents": {json.dumps(dissenting)},\n'
            f'  "consensus_level": "{consensus}",\n'
            f'  "thoughts": "monologue interne",\n'
            f'  "emotion": "CALM|FOCUSED|EXCITED|NERVOUS|PANIC",\n'
            f'  "market_intel": "insight clé"\n}}'
        )
        text = _llm(
            sonnet,
            SONNET_ID,
            [{"role": "user", "content": user_arb}],
            system=system_arb,
            max_tokens=768,
        )
        raw_arb = _parse_json_obj(text)
        arb = validate_decision(raw_arb) if raw_arb else {}

        # validate_decision() runs raw through a Pydantic model whose
        # model_dump() always includes every field, defaulting symbol="" and
        # allocation_pct=0 for any key the LLM's JSON omitted. arb.get(key,
        # fallback) therefore never actually falls back — the key is always
        # present, just with that empty/zero default. Check the *raw* LLM
        # JSON for the key's presence before overriding the pre-LLM
        # composite, so a partial response (e.g. it forgot to repeat symbol)
        # doesn't silently blank out an otherwise-valid BUY (Review Finding).
        final_action = arb.get("action", final_action)
        if raw_arb and raw_arb.get("symbol"):
            symbol = arb.get("symbol", symbol)
        if raw_arb and raw_arb.get("allocation_pct") is not None:
            max_alloc = float(arb.get("allocation_pct", max_alloc))
        composite_conf = float(arb.get("confidence", composite_conf))
        reasoning = arb.get("reasoning", "")
        consensus = arb.get("consensus_level", consensus)
        emotion = arb.get("emotion", "CALM")
        thoughts = arb.get("thoughts", "")
        market_intel = arb.get("market_intel", "")
        dissenting = arb.get("dissenting_agents", dissenting)

        # Deterministic vetoes applied AFTER the LLM has spoken.
        # The pre-LLM dampers (BUY * 0.15/0.5/0.6/0.5 for risk/macro/economic/
        # geo) only nudge the composite score fed to the LLM as context —
        # nothing stops it from still emitting action=BUY at a healthy
        # confidence regardless. Only risk_score > 8 was re-checked here,
        # so the macro/economic/geo/correlation guardrails were effectively
        # advisory in LIVE mode while SIM/PAPER (no LLM) enforce them as hard
        # filters. These overrides are the last line of defence for capital
        # preservation. (Review v5 Finding 4.1; geo/economic extended here)
        if final_action == "BUY" and risk_score > 8:
            logger.warning(
                "RISK VETO (post-LLM): forcing HOLD (risk_score=%s > 8)",
                risk_score,
            )
            final_action = "HOLD"
            composite_conf = 0.3
            logs.append(
                _entry(
                    "arbitrate: RISK VETO (post-LLM) — forced HOLD",
                    "warning",
                )
            )
        elif final_action == "BUY" and geo_risk > 7:
            logger.warning(
                "GEO RISK VETO (post-LLM): forcing HOLD (geo_risk=%s > 7)",
                geo_risk,
            )
            final_action = "HOLD"
            composite_conf = 0.3
            logs.append(
                _entry(
                    "arbitrate: GEO RISK VETO (post-LLM) — forced HOLD",
                    "warning",
                )
            )
        elif final_action == "BUY" and economic_score < -0.5:
            logger.warning(
                "ECONOMIC HEADWIND VETO (post-LLM): forcing HOLD (economic_score=%.2f < -0.5)",
                economic_score,
            )
            final_action = "HOLD"
            composite_conf = 0.3
            logs.append(
                _entry(
                    "arbitrate: ECONOMIC HEADWIND VETO (post-LLM) — forced HOLD",
                    "warning",
                )
            )
        elif final_action == "BUY" and symbol and positions:
            # The LLM can pick a different symbol than the pre-LLM composite
            # checked correlation against — re-check against its actual pick.
            llm_corr = _portfolio_correlation(symbol, list(positions.keys()))
            if llm_corr > 0.7:
                logger.warning(
                    "CORRELATION VETO (post-LLM): forcing HOLD (%s corr=%.2f)",
                    symbol,
                    llm_corr,
                )
                final_action = "HOLD"
                composite_conf = 0.3
                logs.append(
                    _entry(
                        f"arbitrate: CORRELATION VETO (post-LLM) — {symbol} corr={llm_corr:.2f} "
                        "— forced HOLD",
                        "warning",
                    )
                )

    positions = state.get("positions") or {}
    is_pyramid = final_action == "BUY" and bool(symbol) and symbol in positions
    if is_pyramid:
        composite_conf *= 0.8
        logs.append(_entry("arbitrate: pyramide — confiance ×0,8 (renfort sur position ouverte)"))

    arbitration = {
        "action": final_action,
        "symbol": symbol,
        "allocation_pct": min(float(max_alloc), MAX_ALLOC_PCT),
        "confidence": composite_conf,
        "reasoning": reasoning,
        "dissenting_agents": dissenting,
        "consensus_level": consensus,
        "thoughts": thoughts,
        "emotion": emotion,
        "market_intel": market_intel,
        "action_scores": action_scores,
        "_votes": votes,
        "is_pyramid": is_pyramid,
    }

    if final_action == "SELL":
        sizing = str(risk_v.get("sizing_recommendation", "FULL")).upper()
        # SIZING_TO_SELL_PCT["SKIP"] = 0 sizes a BUY the risk_manager wants no
        # part of — it must never neuter an already-decided SELL down to a
        # 0% no-op, exactly when risk is judged worst and exiting matters most.
        risk_sell_pct = 100.0 if sizing == "SKIP" else SIZING_TO_SELL_PCT.get(sizing, 100.0)
        try:
            tech_sell_pct = float(tech_v.get("sell_pct", 100))
        except (TypeError, ValueError):
            tech_sell_pct = 100.0
        tech_sell_pct = max(0.0, min(100.0, tech_sell_pct))
        final_sell_pct = min(risk_sell_pct, tech_sell_pct)
        logs.append(
            _entry(
                f"arbitrate: SELL sizing={sizing} → risk_pct={risk_sell_pct:.0f} "
                f"tech_pct={tech_sell_pct:.0f} → final={final_sell_pct:.0f}"
            )
        )
    else:
        final_sell_pct = 100.0

    decision = {
        "action": final_action,
        "symbol": symbol,
        "allocation_pct": min(float(max_alloc), MAX_ALLOC_PCT),
        "sell_pct": final_sell_pct,
        "confidence": composite_conf,
        "reasoning": arbitration["reasoning"],
        "thoughts": thoughts,
        "emotion": emotion,
        "market_intel": market_intel,
        "is_pyramid": is_pyramid,
    }
    arbitration["sell_pct"] = final_sell_pct

    # ── PHASE 5 : décision finale ─────────────────────────────────────────────
    # Si confiance < 0.72 et qu'on n'a pas encore fait de recherche, on renvoie
    # vers research_node (web search Sonnet) avant risk_check — max 2 itérations.
    skip_res = state.get("skip_research", False) or composite_conf >= 0.72

    # ``was_correct`` is no longer set here — it was tautological (consensus
    # check, not market performance). Evaluation now happens asynchronously
    # against the actual price move (see ``pending_evaluations`` table and
    # the evaluation job).

    logs.append(
        _entry(
            f"arbitrate: {final_action} {symbol} conf={composite_conf:.0%} "
            f"consensus={consensus} dissenting={dissenting}"
        )
    )
    if thoughts:
        logs.append(_entry(f"thoughts: {thoughts[:120]}"))

    _persist_cycle_state(state["round"], arbitration, votes, action_scores)

    return {
        "arbitration": arbitration,
        "decision": decision,
        "confidence": composite_conf,
        "emotion": emotion,
        "thoughts": thoughts,
        "skip_research": skip_res,
        "log": logs,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DAILY DIGEST (Discord)
# ═══════════════════════════════════════════════════════════════════════════════


def _today_realized_pnl_pcts(portfolio: Portfolio) -> list[float]:
    """Percent P&L for each SELL executed today (vs the reconstructed
    share-weighted entry for the position it closed — see
    ``_reconstruct_avg_entry``, not just the last BUY anywhere in history).
    """

    today = date.today().isoformat()
    pnls: list[float] = []
    for trade in portfolio.trade_history:
        if trade.get("action") != "SELL":
            continue
        t = str(trade.get("time") or "")
        if not t.startswith(today):
            continue
        symbol = trade.get("symbol")
        try:
            sp = float(trade.get("price"))
        except (TypeError, ValueError):
            continue
        try:
            sell_time = datetime.fromisoformat(t)
        except ValueError:
            continue
        entry = _reconstruct_avg_entry(portfolio.trade_history, symbol, sell_time)
        if entry is None:
            continue
        bp, _ = entry
        if bp > 0:
            pnls.append((sp - bp) / bp * 100.0)
    return pnls


def run_daily_digest(portfolio: Portfolio) -> None:
    """Build and send the Discord daily digest (skipped in simulation mode)."""

    if _sim_mode["enabled"]:
        return

    from agents.shared.nodes import get_consecutive_hold_cycles, get_daily_start_value

    try:
        from core.notifications import alert_daily_digest
    except Exception:
        return

    prices = portfolio.fetch_prices(get_watchlist())
    portfolio_value = float(portfolio.total_value(prices))
    today = date.today()
    date_str = today.isoformat()

    start_val, start_date = get_daily_start_value()
    if start_val is not None and start_date == date_str:
        baseline = float(start_val)
        pnl_usd = portfolio_value - baseline
        pnl_pct = (pnl_usd / baseline * 100.0) if baseline > 0 else 0.0
    else:
        pnl_usd = 0.0
        pnl_pct = 0.0

    rows = _db_read(
        "SELECT action, symbol, price, sell_pct FROM trades "
        "WHERE substr(timestamp, 1, 10) = ? ORDER BY id ASC",
        (date_str,),
    )
    trades_summary: list[dict] = []
    for row in rows:
        action, symbol, price, sell_pct = row[0], row[1], row[2], row[3]
        au = (action or "").upper()
        sp_out: float | None = None
        if au == "SELL" and sell_pct is not None:
            try:
                spv = float(sell_pct)
            except (TypeError, ValueError):
                spv = 100.0
            if spv < 100.0:
                sp_out = spv
        try:
            px = float(price) if price is not None else 0.0
        except (TypeError, ValueError):
            px = 0.0
        trades_summary.append(
            {
                "action": au or "HOLD",
                "symbol": symbol or "",
                "price": px,
                "sell_pct": sp_out,
            }
        )

    # Snapshot under the lock — this runs in the postmortem thread while the
    # agent thread can concurrently mutate portfolio.positions (a full SELL
    # does `del self.positions[symbol]`), so iterating the live dict
    # directly risked "dictionary changed size during iteration".
    with portfolio._lock:
        positions_snapshot = dict(portfolio.positions)

    positions: dict[str, dict] = {}
    for sym, pos in positions_snapshot.items():
        avg = float(pos.get("avg_price", pos.get("avg_cost", 0)))
        sh = float(pos.get("shares", 0))
        cur = float(prices.get(sym, avg))
        pnl_p = ((cur - avg) / avg * 100.0) if avg > 0 else 0.0
        positions[sym] = {
            "shares": sh,
            "avg_price": avg,
            "current": cur,
            "pnl_pct": round(pnl_p, 2),
        }

    try:
        agent_accuracy = _read_agent_accuracies()
    except Exception:
        agent_accuracy = {k: None for k in WEIGHTS}

    mode = get_runtime_mode()
    mode_label = mode.upper() if mode else "LIVE"

    fg: dict | None = None
    try:
        from core.external_data import fetch_fear_greed as _fetch_fg

        fg = _fetch_fg()
    except Exception:
        pass

    alert_daily_digest(
        date=date_str,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        portfolio_value=portfolio_value,
        trades_summary=trades_summary,
        positions=positions,
        agent_accuracy=agent_accuracy,
        consecutive_holds=get_consecutive_hold_cycles(),
        mode=mode_label,
        realized_pnl_pcts=_today_realized_pnl_pcts(portfolio),
        fear_greed=fg,
    )


def _spy_week_return_pct() -> float | None:
    """Approximate SPY return over ``yf.download(..., period=\"5d\")`` window."""

    try:
        raw = yf.download(
            "SPY",
            period="5d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        if raw is None or len(raw) < 2:
            return None
        df = raw
        try:
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        except (AttributeError, TypeError, ValueError):
            pass
        closes = df["Close"].dropna()
        if len(closes) < 2:
            return None
        first = float(closes.iloc[0])
        last = float(closes.iloc[-1])
        if first <= 0:
            return None
        return (last - first) / first * 100.0
    except Exception:
        return None


def _rolling_7d_closed_sell_pnls(portfolio: Portfolio) -> list[tuple[str, float]]:
    """Symbol and realized P&L % for each SELL in the last 7 days (vs the
    reconstructed share-weighted entry for the position it closed — see
    ``_reconstruct_avg_entry``, not just the last BUY anywhere in history).
    """

    cutoff = datetime.now() - timedelta(days=7)
    out: list[tuple[str, float]] = []
    for trade in portfolio.trade_history:
        if trade.get("action") != "SELL":
            continue
        tstr = str(trade.get("time") or "")
        try:
            tnorm = tstr.replace("Z", "+00:00")
            tt = datetime.fromisoformat(tnorm)
            if tt.tzinfo:
                tt = tt.replace(tzinfo=None)
        except ValueError:
            try:
                tt = datetime.fromisoformat(tstr[:19])
            except ValueError:
                continue
        if tt < cutoff:
            continue
        symbol = trade.get("symbol")
        try:
            sp = float(trade.get("price"))
        except (TypeError, ValueError):
            continue
        entry = _reconstruct_avg_entry(portfolio.trade_history, symbol, tt)
        if entry is None:
            continue
        bp, _ = entry
        if bp > 0 and symbol:
            out.append((str(symbol), (sp - bp) / bp * 100.0))
    return out


def _week_agent_ranking() -> list[dict]:
    """Per-agent accuracy (evaluated votes) and activity in the rolling 7-day window."""

    rows_acc = _db_read(
        "SELECT agent_name, AVG(was_correct), COUNT(*) FROM agent_memory "
        "WHERE date(timestamp) >= date('now', '-7 days') AND was_correct IS NOT NULL "
        "GROUP BY agent_name"
    )
    rows_vol = _db_read(
        "SELECT agent_name, COUNT(*) FROM agent_memory "
        "WHERE date(timestamp) >= date('now', '-7 days') GROUP BY agent_name"
    )
    vol_by = {str(r[0]): int(r[1]) for r in rows_vol}
    ranking: list[dict] = []
    seen: set[str] = set()
    for r in rows_acc:
        name = str(r[0])
        seen.add(name)
        ranking.append(
            {
                "name": name,
                "accuracy": float(r[1]),
                "trades": vol_by.get(name, int(r[2])),
            }
        )
    for name, cnt in vol_by.items():
        if name not in seen:
            ranking.append({"name": name, "accuracy": None, "trades": cnt})
    for agent in WEIGHTS:
        if not any(x["name"] == agent for x in ranking):
            ranking.append({"name": agent, "accuracy": None, "trades": 0})
    ranking.sort(key=lambda x: (x["accuracy"] is None, -(x["accuracy"] or 0.0)))
    return ranking


def run_weekly_report(portfolio: Portfolio) -> None:
    """Build and send the Discord weekly performance report (skipped in simulation)."""

    if _sim_mode["enabled"]:
        return

    try:
        from core.notifications import alert_weekly_report
    except Exception:
        return

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_start = monday.isoformat()
    week_end = today.isoformat()

    prices = portfolio.fetch_prices(get_watchlist())
    portfolio_value = float(portfolio.total_value(prices))

    wval, wkey = get_weekly_start_value()
    if wval is not None and wkey == week_start:
        baseline = float(wval)
        pnl_usd = portfolio_value - baseline
        pnl_pct = (pnl_usd / baseline * 100.0) if baseline > 0 else 0.0
    else:
        pnl_usd = 0.0
        pnl_pct = 0.0

    exec_rows = _db_read(
        "SELECT COUNT(*) FROM trades WHERE date(timestamp) >= date('now', '-7 days')"
    )
    total_trades = int(exec_rows[0][0]) if exec_rows else 0

    closed = _rolling_7d_closed_sell_pnls(portfolio)
    wins = sum(1 for _, p in closed if p > 0)
    n_closed = len(closed)
    win_rate = (wins / n_closed) if n_closed else 0.0

    best_trade: dict | None = None
    worst_trade: dict | None = None
    if closed:
        best_sym, best_p = max(closed, key=lambda x: x[1])
        worst_sym, worst_p = min(closed, key=lambda x: x[1])
        best_trade = {"symbol": best_sym, "pnl_pct": round(best_p, 2)}
        worst_trade = {"symbol": worst_sym, "pnl_pct": round(worst_p, 2)}

    agent_ranking = _week_agent_ranking()
    spy_pct = _spy_week_return_pct()

    mode = get_runtime_mode()
    mode_label = mode.upper() if mode else "LIVE"

    alert_weekly_report(
        week_start=week_start,
        week_end=week_end,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        portfolio_value=portfolio_value,
        total_trades=total_trades,
        win_rate=win_rate,
        win_count=wins,
        closed_trades=n_closed,
        best_trade=best_trade,
        worst_trade=worst_trade,
        agent_ranking=agent_ranking,
        spy_pct=spy_pct,
        mode=mode_label,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DAILY POSTMORTEM
# ═══════════════════════════════════════════════════════════════════════════════


def _reconstruct_avg_entry(
    trade_history: list[dict], symbol: str, sell_time: datetime
) -> tuple[float, datetime] | None:
    """Weighted-average cost basis + first-open time for a position closed
    by the SELL at ``sell_time``.

    Walks ``trade_history`` chronologically, accumulating BUY layers (so
    pyramided positions get their true blended entry, not just the last
    layer's price) since the position was last fully flat — an earlier
    SELL for the same symbol resets the accumulator, so a same-day
    re-entry doesn't get matched against a prior, already-closed cycle's
    buys. Returns ``None`` if no open position is found before ``sell_time``.
    """
    open_shares = 0.0
    open_cost = 0.0
    first_buy_time: datetime | None = None
    for t in trade_history:
        if t.get("symbol") != symbol:
            continue
        t_time = datetime.fromisoformat(t["time"])
        if t_time >= sell_time:
            break
        if t["action"] == "BUY":
            shares = float(t.get("shares", 0.0))
            price = float(t.get("price", 0.0))
            if open_shares <= 1e-9:
                first_buy_time = t_time
            open_shares += shares
            open_cost += shares * price
        elif t["action"] == "SELL" and open_shares > 0:
            sold_shares = float(t.get("shares", 0.0))
            frac = min(sold_shares / open_shares, 1.0)
            open_cost *= 1 - frac
            open_shares -= sold_shares
            if open_shares <= 1e-9:
                open_shares = 0.0
                open_cost = 0.0

    if open_shares <= 1e-9 or first_buy_time is None:
        return None
    return open_cost / open_shares, first_buy_time


def run_daily_postmortem(portfolio: Portfolio) -> None:
    """Generate postmortem entries for all SELL trades since midnight.

    Uses ``_get_db_path()`` so sim-mode writes go to ``trades_sim.db``.
    """
    midnight = datetime.combine(date.today(), datetime.min.time()).isoformat()
    if _paper_mode["enabled"]:
        source = "paper"
    elif _sim_mode["enabled"]:
        source = "simulation"
    else:
        source = "live"

    sells = portfolio.closed_trades_since(midnight)
    if not sells:
        return

    for trade in sells:
        symbol = trade["symbol"]
        sell_price = trade["price"]
        sell_time = datetime.fromisoformat(trade["time"])

        entry = _reconstruct_avg_entry(portfolio.trade_history, symbol, sell_time)
        if entry is None:
            continue
        buy_price, buy_time = entry
        holding_hours = (sell_time - buy_time).total_seconds() / 3600
        pnl_pct = ((sell_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0

        # Scope to THIS trade's own cycle, not just the symbol: without a
        # trace_id filter, this pulled was_correct=1 SELL votes from ANY past
        # trade on the symbol — including cycles that had nothing to do with
        # today's decision, misattributing unrelated historical agents as
        # if they were behind this specific sell (Review Finding). was_correct
        # for THIS trade's own trace_id isn't resolved yet (evaluate_pending_
        # trades runs ~EVAL_HORIZON_CALENDAR_DAYS later), so scope by trace_id
        # + vote='SELL' — the agents who actually recommended this exact
        # trade — instead of a stale, unrelated "was correct historically"
        # signal.
        trace_rows = _db_read(
            "SELECT trace_id FROM trades WHERE symbol=? AND action='SELL' "
            "AND timestamp >= ? ORDER BY timestamp ASC LIMIT 1",
            (symbol, trade["time"]),
        )
        trace_id = trace_rows[0][0] if trace_rows and trace_rows[0][0] else None
        if trace_id:
            rows = _db_read(
                "SELECT agent_name FROM agent_memory "
                "WHERE trace_id=? AND vote='SELL' "
                "ORDER BY timestamp DESC LIMIT 4",
                (trace_id,),
            )
        else:
            rows = []
        agents_correct = json.dumps([r[0] for r in rows])

        if _no_llm_mode():
            tag = "PAPER" if _paper_mode["enabled"] else "SIM"
            summary = f"[{tag}] P&L {pnl_pct:+.2f}% sur {holding_hours:.1f}h — signal RSI."
        else:
            prompt = (
                f"Postmortem de trade — {symbol}\n"
                f"Achat: ${buy_price:.2f} | Vente: ${sell_price:.2f} | "
                f"P&L: {pnl_pct:+.2f}% | Durée: {holding_hours:.1f}h\n"
                f"Agents corrects: {agents_correct}\n\n"
                "En 2 phrases maximum, quelle leçon retenir de ce trade ? "
                "Sois factuel et critique."
            )
            summary = _llm(
                haiku, HAIKU_ID, [{"role": "user", "content": prompt}], max_tokens=120
            ).strip()

        _db_write(
            "INSERT INTO postmortem "
            "(timestamp,symbol,buy_price,sell_price,pnl_pct,holding_hours,"
            "agents_correct,summary,source) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                _ts(),
                symbol,
                buy_price,
                sell_price,
                round(pnl_pct, 4),
                round(holding_hours, 4),
                agents_correct,
                summary,
                source,
            ),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════════════════════


def _route_arbitrate(state: MultiAgentState) -> str:
    # In SIM/PAPER only technician+analyst feed the composite confidence
    # score (weights 0.28+0.32 = 0.60 total — risk/macro/economist/geo only
    # contribute to the HOLD baseline), so it can never reach the 0.72 gate
    # on its own. Without this bypass every single SIM/PAPER cycle fell
    # through to research → sim_research(), which doesn't do real research
    # (no LLM available) — it just overwrites the real computed confidence
    # with a flat 0.75 on every cycle instead of the gate ever meaningfully
    # applying (Review Finding). Skip the pointless detour and keep the
    # genuine composite score.
    if _no_llm_mode():
        return "risk_check"
    conf = state.get("confidence", 0.0)
    iters = state.get("research_iterations", 0)
    skip = state.get("skip_research", False)
    if skip or conf >= 0.72 or iters >= 2:
        return "risk_check"
    return "research"


# ═══════════════════════════════════════════════════════════════════════════════
# GRAPH BUILDER
# ═══════════════════════════════════════════════════════════════════════════════


def build_multi_graph(portfolio: Portfolio):
    g = StateGraph(MultiAgentState)

    # Reused nodes from shared/
    g.add_node("load_memory", load_memory_node)
    g.add_node("fetch_data", make_fetch_data_node(portfolio))
    g.add_node("execute", make_execute_node(portfolio))
    g.add_node("save_memory", make_save_memory_node(portfolio))
    g.add_node("risk_check", risk_check_node)
    g.add_node("skip", make_skip_node(portfolio))
    g.add_node("research", research_node)

    # Multi-agent specific nodes
    g.add_node("supervisor", supervisor_node)
    g.add_node("technician", technician_node)
    g.add_node("analyst", analyst_node)
    g.add_node("risk_manager", risk_manager_node)
    g.add_node("macro_watcher", macro_watcher_node)
    g.add_node("economist", economist_node)
    g.add_node("geopolitician", geopolitician_node)
    g.add_node("arbitrate", arbitrate_node)

    # Edges: linear start
    g.add_edge(START, "load_memory")
    g.add_edge("load_memory", "fetch_data")
    g.add_edge("fetch_data", "supervisor")

    # Fan-out from supervisor to 6 parallel agents
    g.add_conditional_edges(
        "supervisor",
        _route_to_agents,
        ["technician", "analyst", "risk_manager", "macro_watcher", "economist", "geopolitician"],
    )

    # Fan-in: all 6 parallel agents → arbitrate
    g.add_edge("technician", "arbitrate")
    g.add_edge("analyst", "arbitrate")
    g.add_edge("risk_manager", "arbitrate")
    g.add_edge("macro_watcher", "arbitrate")
    g.add_edge("economist", "arbitrate")
    g.add_edge("geopolitician", "arbitrate")

    # Arbitrate routing: confident → risk_check, uncertain → research → risk_check
    g.add_conditional_edges(
        "arbitrate",
        _route_arbitrate,
        {"risk_check": "risk_check", "research": "research"},
    )
    g.add_edge("research", "risk_check")

    # Risk check → execute or skip
    g.add_conditional_edges(
        "risk_check",
        _route_risk,
        {"execute": "execute", "skip": "skip"},
    )
    g.add_edge("execute", "save_memory")
    g.add_edge("save_memory", END)
    g.add_edge("skip", END)

    return g.compile()


# Alias for test compatibility
build_graph = build_multi_graph

# LangGraph Studio compatibility
try:
    agent_multi_graph = build_multi_graph(Portfolio())
except Exception:
    agent_multi_graph = None
