"""APEX-7 // MULTI-AGENT GRAPH — 4 specialized agents + arbitration (extracted from agent_multi.py)."""

import json
import random
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents.shared.nodes import (
    DB_PATH,
    HAIKU_ID,
    SONNET_ID,
    _entry,
    _llm,
    _parse_json_obj,
    _portfolio_value,
    _route_risk,
    _sim_mode,
    _sim_price_history,
    _sim_rsi,
    _ts,
    haiku,
    load_memory_node,
    make_execute_node,
    make_fetch_data_node,
    make_save_memory_node,
    research_node,
    risk_check_node,
    skip_node,
    sonnet,
)
from agents.shared.state import MultiAgentState
from config import (
    DEATH_THRESHOLD,
    INITIAL_BALANCE,
    MAX_ALLOC_PCT,
    MAX_POSITIONS,
    WATCHLIST,
)
from core.data import Portfolio

# ═══════════════════════════════════════════════════════════════════════════════
# WEIGHTS
# ═══════════════════════════════════════════════════════════════════════════════

WEIGHTS = {
    "technician": 0.30,
    "analyst": 0.35,
    "risk_manager": 0.20,  # does NOT vote on direction
    "macro_watcher": 0.15,
}

_cached_weights: dict = {}
_weights_computed_at: float = 0.0


def _compute_dynamic_weights(db_path: Path) -> dict:
    """Compute agent weights blended with historical accuracy from agent_memory.

    Uses a 10-minute cache. Falls back to static WEIGHTS if an agent has
    fewer than 5 scored votes. Blend: 70% static + 30% accuracy-based.
    Always returns a dict normalised to sum=1.0.
    """
    global _cached_weights, _weights_computed_at

    if _cached_weights and (time.time() - _weights_computed_at) < 600:
        return _cached_weights

    agents = list(WEIGHTS.keys())
    accuracy: dict[str, float] = {}

    try:
        con = sqlite3.connect(db_path)
        for agent in agents:
            rows = con.execute(
                "SELECT was_correct FROM agent_memory "
                "WHERE agent_name=? AND was_correct IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 50",
                (agent,),
            ).fetchall()
            if len(rows) >= 5:
                accuracy[agent] = sum(r[0] for r in rows) / len(rows)
            else:
                accuracy[agent] = None  # type: ignore[assignment]
        con.close()
    except Exception:
        # DB not available — fall back to static weights entirely
        _cached_weights = dict(WEIGHTS)
        _weights_computed_at = time.time()
        return _cached_weights

    # Agents with enough data contribute their accuracy; others use static weight
    valid_accuracies = {a: v for a, v in accuracy.items() if v is not None}
    sum_accuracies = sum(valid_accuracies.values()) if valid_accuracies else 1.0
    if sum_accuracies == 0.0:
        sum_accuracies = 1.0

    dynamic: dict[str, float] = {}
    for agent in agents:
        static_w = WEIGHTS[agent]
        if accuracy[agent] is not None:
            acc_norm = accuracy[agent] / sum_accuracies
            dynamic[agent] = 0.7 * static_w + 0.3 * acc_norm
        else:
            dynamic[agent] = static_w

    # Normalise to sum=1.0
    total = sum(dynamic.values())
    if total > 0:
        dynamic = {a: v / total for a, v in dynamic.items()}

    _cached_weights = dynamic
    _weights_computed_at = time.time()
    return _cached_weights


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def sim_technician(state: MultiAgentState) -> dict:
    prices = state["prices"]
    pos = state["positions"]
    logs = [_entry("[SIM][TECH] RSI-based technical analysis")]

    rsi_map = {
        sym: _sim_rsi(_sim_price_history.get(sym, [prices.get(sym, 100.0)]))
        for sym in WATCHLIST
        if sym in prices
    }

    oversold = {s: r for s, r in rsi_map.items() if r < 35}
    overbought = {s: r for s, r in rsi_map.items() if r > 65 and s in pos}

    if overbought:
        sym = min(overbought, key=overbought.get)
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
        sym = WATCHLIST[0] if WATCHLIST else ""
        action, conf, alloc = "HOLD", 0.58, 0
        rsi_v = rsi_map.get(sym, 50.0)
        reason = f"RSI={rsi_v:.1f} — neutral zone, no setup"
        macd, bb, trend = "neutral", "mid", "sideways"

    vote = {
        "agent": "technician",
        "agent_name": "Technician",
        "action": action,
        "symbol": sym,
        "confidence": conf,
        "allocation_pct": alloc,
        "reasoning": reason,
        "signals": [
            f"RSI({rsi_v:.1f}): {'oversold' if rsi_v < 35 else 'overbought' if rsi_v > 65 else 'neutral'}",
            f"MACD: {macd}",
            f"Bollinger Band: {bb}",
            f"Trend: {trend}",
        ],
        "key_indicators": {"rsi": round(rsi_v, 1), "macd": macd, "bb": bb, "trend": trend},
    }
    logs.append(_entry(f"[SIM][TECH] {action} {sym} conf={conf:.0%} RSI={rsi_v:.1f}"))
    try:
        _con = sqlite3.connect(DB_PATH)
        _con.execute(
            "INSERT INTO agent_memory (timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source) "
            "VALUES (?,?,?,?,?,NULL,NULL,?)",
            (_ts(), "technician", sym, action, float(conf), "simulation"),
        )
        _con.commit()
        _con.close()
    except Exception:
        pass
    return {"agent_votes": [vote], "tech_vote": vote, "log": logs}


def sim_analyst(state: MultiAgentState) -> dict:
    prices = state["prices"]
    pos = state["positions"]
    sentiment = state.get("sentiment", {})
    logs = [_entry("[SIM][ANLST] sentiment-based fundamental analysis")]

    avg_sent = sum(sentiment.values()) / max(len(sentiment), 1)

    if avg_sent > 0.15 and len(pos) < MAX_POSITIONS:
        candidates = [s for s in WATCHLIST if s not in pos and s in prices]
        sym = random.choice(candidates) if candidates else (WATCHLIST[0] if WATCHLIST else "")
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
        sym = WATCHLIST[0] if WATCHLIST else ""
        action = "HOLD"
        conf = 0.55
        alloc = 0
        reason = f"Mixed sentiment ({avg_sent:+.2f}) — no clear fundamental catalyst"
        catalysts = []

    vote = {
        "agent": "analyst",
        "agent_name": "Analyst",
        "action": action,
        "symbol": sym,
        "confidence": conf,
        "allocation_pct": alloc,
        "reasoning": reason,
        "signals": [
            f"Aggregate sentiment: {avg_sent:+.2f}",
            f"Market bias: {'bullish' if avg_sent > 0.15 else 'bearish' if avg_sent < -0.15 else 'neutral'}",
        ]
        + catalysts,
        "catalysts": catalysts,
        "sentiment_score": round(avg_sent, 2),
    }
    logs.append(_entry(f"[SIM][ANLST] {action} {sym} conf={conf:.0%} sent={avg_sent:+.2f}"))
    try:
        _con = sqlite3.connect(DB_PATH)
        _con.execute(
            "INSERT INTO agent_memory (timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source) "
            "VALUES (?,?,?,?,?,NULL,NULL,?)",
            (_ts(), "analyst", sym, action, float(conf), "simulation"),
        )
        _con.commit()
        _con.close()
    except Exception:
        pass
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

    vote = {
        "agent": "risk_manager",
        "agent_name": "Risk Manager",
        "risk_score": risk_score,
        "max_safe_allocation_pct": float(max_alloc),
        "var_1d": round(var_1d, 2),
        "portfolio_exposure_after": round(exposure * 100, 1),
        "sizing_recommendation": sizing,
        "reasoning": reason,
        "signals": [
            f"Risk score: {risk_score}/10",
            f"Portfolio danger ratio: {danger_ratio:.2f} (death at {DEATH_THRESHOLD/INITIAL_BALANCE:.2f})",
            f"Exposure: {exposure:.0%}",
            f"VaR 95% 1d: ${var_1d:.0f}",
            f"Sizing: {sizing}",
        ]
        + warnings,
        "warnings": warnings,
        # risk_manager votes HOLD (doesn't pick direction)
        "action": "HOLD",
        "symbol": "",
        "confidence": 0.5,
        "allocation_pct": max_alloc,
    }
    logs.append(_entry(f"[SIM][RISK] score={risk_score}/10 sizing={sizing} VaR=${var_1d:.0f}"))
    try:
        _con = sqlite3.connect(DB_PATH)
        _con.execute(
            "INSERT INTO agent_memory (timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source) "
            "VALUES (?,?,?,?,?,NULL,NULL,?)",
            (_ts(), "risk_manager", "", "HOLD", 0.5, "simulation"),
        )
        _con.commit()
        _con.close()
    except Exception:
        pass
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

    vote = {
        "agent": "macro_watcher",
        "agent_name": "Macro Watcher",
        "market_regime": regime,
        "macro_bias": bias,
        "recommended_exposure": exposure,
        "sector_rotation": rotation,
        "reasoning": reason,
        "signals": [
            f"Market regime: {regime}",
            f"Macro bias: {bias}",
            f"Portfolio health: {pv/INITIAL_BALANCE:.0%} of initial capital",
            f"Aggregate sentiment: {avg_sent:+.2f}",
            f"Recommended exposure: {exposure}%",
            f"Sector rotation: {rotation}",
        ],
        "macro_score": round(macro_score, 2),
        # macro_watcher also doesn't vote on specific direction
        "action": "HOLD",
        "symbol": "",
        "confidence": 0.5,
        "allocation_pct": 0,
    }
    logs.append(_entry(f"[SIM][MACRO] {regime} {bias} exposure={exposure}%"))
    try:
        _con = sqlite3.connect(DB_PATH)
        _con.execute(
            "INSERT INTO agent_memory (timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source) "
            "VALUES (?,?,?,?,?,NULL,NULL,?)",
            (_ts(), "macro_watcher", "", "HOLD", 0.5, "simulation"),
        )
        _con.commit()
        _con.close()
    except Exception:
        pass
    return {"agent_votes": [vote], "macro_vote": vote, "log": logs}


# ═══════════════════════════════════════════════════════════════════════════════
# SUPERVISOR NODE
# ═══════════════════════════════════════════════════════════════════════════════


def supervisor_node(state: MultiAgentState) -> dict:
    logs = [_entry("supervisor: preparing context brief for team")]

    if _sim_mode["enabled"]:
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
        f"News snippet: {(state.get('news') or 'N/A')[:200]}\n\n"
        "Résume en 3 points clés ce contexte de marché pour briefer ton équipe de traders. "
        "Sois factuel et concis (max 60 mots)."
    )
    brief = _llm(haiku, HAIKU_ID, [{"role": "user", "content": prompt}], max_tokens=120)
    logs.append(_entry(f"supervisor: brief ready ({len(brief)} chars)"))
    return {"supervisor_brief": brief, "log": logs}


def _route_to_agents(state: MultiAgentState) -> list:
    """Fan-out via Send to 4 parallel agents."""
    base = dict(state)
    return [
        Send("technician", {**base, "agent_role": "technician"}),
        Send("analyst", {**base, "agent_role": "analyst"}),
        Send("risk_manager", {**base, "agent_role": "risk_manager"}),
        Send("macro_watcher", {**base, "agent_role": "macro_watcher"}),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# PARALLEL AGENT NODES
# ═══════════════════════════════════════════════════════════════════════════════


def technician_node(state: MultiAgentState) -> dict:
    if _sim_mode["enabled"]:
        return sim_technician(state)

    prices = state["prices"]
    pos = state["positions"]
    logs = [_entry("technician: technical analysis")]

    _con = sqlite3.connect(DB_PATH)
    _rows = _con.execute(
        "SELECT lesson FROM agent_memory WHERE agent_name='technician' AND lesson IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT 5"
    ).fetchall()
    _con.close()
    recent_lessons = [r[0] for r in _rows if r[0]]

    rsi_map = {
        sym: _sim_rsi(_sim_price_history.get(sym, [prices.get(sym, 100.0)]))
        for sym in WATCHLIST
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

    system = (
        "Tu es un trader quantitatif expert en analyse technique. "
        "Tu ne regardes QUE les prix, volumes et indicateurs techniques. "
        "Tu ignores les news et le macro. Tu es méthodique, précis, factuel. "
        "Retourne UNIQUEMENT du JSON valide."
    )
    if recent_lessons:
        system += "\nTes erreurs récentes :\n" + "\n".join(
            f"  • {lesson}" for lesson in recent_lessons
        )
    user = (
        f"TECHNICAL ANALYSIS — Cycle #{state['round']}\n\n"
        f"PRIX ACTUELS:\n{json.dumps({s: f'${p:.2f}' for s, p in prices.items()}, indent=2)}\n\n"
        f"RSI(14) par symbole:\n{json.dumps({s: round(r, 1) for s, r in rsi_map.items()}, indent=2)}\n\n"
        f"POSITIONS ACTUELLES:\n{json.dumps(positions_display, indent=2)}\n\n"
        f"WATCHLIST: {WATCHLIST}\n"
        f"POSITIONS MAX: {MAX_POSITIONS} | ACTUELLES: {len(pos)}\n\n"
        "Retourne ce JSON uniquement :\n"
        '{\n  "agent": "technician",\n  "action": "BUY|SELL|HOLD",\n'
        '  "symbol": "TICKER",\n  "confidence": 0.0,\n  "allocation_pct": 10,\n'
        '  "reasoning": "2 phrases",\n'
        '  "key_indicators": {"rsi": 0.0, "macd": "bullish|bearish|neutral", '
        '"bb": "lower|mid|upper", "trend": "up|down|sideways"}\n}'
    )

    text = _llm(haiku, HAIKU_ID, [{"role": "user", "content": user}], system=system, max_tokens=512)
    vote = _parse_json_obj(text)
    if not vote:
        vote = {
            "agent": "technician",
            "action": "HOLD",
            "symbol": "",
            "confidence": 0.5,
            "allocation_pct": 0,
            "reasoning": "Parse error — defaulting to HOLD",
            "key_indicators": {"rsi": 50.0, "macd": "neutral", "bb": "mid", "trend": "sideways"},
        }
    vote["agent"] = "technician"
    vote["agent_name"] = "Technician"
    ki = vote.get("key_indicators", {})
    rsi_val = ki.get("rsi") or rsi_map.get(vote.get("symbol", ""), 50.0)
    vote.setdefault(
        "signals",
        [
            f"RSI({rsi_val:.1f}): {'oversold' if rsi_val < 35 else 'overbought' if rsi_val > 65 else 'neutral'}",
            f"MACD: {ki.get('macd', 'N/A')}",
            f"Bollinger Band: {ki.get('bb', 'N/A')}",
            f"Trend: {ki.get('trend', 'N/A')}",
        ],
    )
    logs.append(
        _entry(
            f"technician: {vote.get('action')} {vote.get('symbol','')} conf={vote.get('confidence',0):.0%}"
        )
    )
    try:
        _con = sqlite3.connect(DB_PATH)
        _con.execute(
            "INSERT INTO agent_memory (timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source) "
            "VALUES (?,?,?,?,?,NULL,NULL,?)",
            (
                _ts(),
                "technician",
                vote.get("symbol", ""),
                vote.get("action", "HOLD"),
                float(vote.get("confidence", 0.5)),
                "live",
            ),
        )
        _con.commit()
        _con.close()
    except Exception:
        pass
    return {"agent_votes": [vote], "tech_vote": vote, "log": logs}


def analyst_node(state: MultiAgentState) -> dict:
    if _sim_mode["enabled"]:
        return sim_analyst(state)

    pos = state["positions"]
    sentiment = state.get("sentiment", {})
    logs = [_entry("analyst: fundamental + sentiment analysis")]

    _con = sqlite3.connect(DB_PATH)
    _rows = _con.execute(
        "SELECT lesson FROM agent_memory WHERE agent_name='analyst' AND lesson IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT 5"
    ).fetchall()
    _con.close()
    recent_lessons = [r[0] for r in _rows if r[0]]

    system = (
        "Tu es un analyste financier fondamental senior. "
        "Tu analyses les catalyseurs, earnings, actualités, sentiment de marché. "
        "Tu ignores les indicateurs techniques. "
        "Tu penses en termes de valeur intrinsèque et de catalyseurs. "
        "Retourne UNIQUEMENT du JSON valide."
    )
    if recent_lessons:
        system += "\nTes erreurs récentes :\n" + "\n".join(
            f"  • {lesson}" for lesson in recent_lessons
        )
    user = (
        f"FUNDAMENTAL ANALYSIS — Cycle #{state['round']}\n\n"
        f"NEWS RÉCENTES:\n{(state.get('news') or 'Aucune news')[:600]}\n\n"
        f"SENTIMENT TWITTER (-1=baissier → +1=haussier):\n"
        f"{json.dumps(sentiment, indent=2)}\n\n"
        f"POSITIONS ACTUELLES: {list(pos.keys())}\n"
        f"WATCHLIST: {WATCHLIST} | POSITIONS MAX: {MAX_POSITIONS}\n\n"
        f"BRIEF SUPERVISEUR:\n{state.get('supervisor_brief', '')}\n\n"
        "Retourne ce JSON uniquement :\n"
        '{\n  "agent": "analyst",\n  "action": "BUY|SELL|HOLD",\n'
        '  "symbol": "TICKER",\n  "confidence": 0.0,\n  "allocation_pct": 10,\n'
        '  "reasoning": "2 phrases",\n  "catalysts": ["catalyst1"],\n'
        '  "sentiment_score": 0.0\n}'
    )

    text = _llm(
        sonnet,
        SONNET_ID,
        [{"role": "user", "content": user}],
        system=system,
        max_tokens=512,
        web_search=True,
    )
    vote = _parse_json_obj(text)
    if not vote:
        vote = {
            "agent": "analyst",
            "action": "HOLD",
            "symbol": "",
            "confidence": 0.5,
            "allocation_pct": 0,
            "reasoning": "Parse error — defaulting to HOLD",
            "catalysts": [],
            "sentiment_score": 0.0,
        }
    vote["agent"] = "analyst"
    vote["agent_name"] = "Analyst"
    sent_score = vote.get("sentiment_score", 0.0)
    catalysts_list = vote.get("catalysts", [])
    vote.setdefault(
        "signals",
        [
            f"Sentiment score: {sent_score:+.2f}",
            f"Market bias: {'bullish' if sent_score > 0.15 else 'bearish' if sent_score < -0.15 else 'neutral'}",
        ]
        + catalysts_list,
    )
    logs.append(
        _entry(
            f"analyst: {vote.get('action')} {vote.get('symbol','')} conf={vote.get('confidence',0):.0%}"
        )
    )
    try:
        _con = sqlite3.connect(DB_PATH)
        _con.execute(
            "INSERT INTO agent_memory (timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source) "
            "VALUES (?,?,?,?,?,NULL,NULL,?)",
            (
                _ts(),
                "analyst",
                vote.get("symbol", ""),
                vote.get("action", "HOLD"),
                float(vote.get("confidence", 0.5)),
                "live",
            ),
        )
        _con.commit()
        _con.close()
    except Exception:
        pass
    return {"agent_votes": [vote], "analyst_vote": vote, "log": logs}


def risk_manager_node(state: MultiAgentState) -> dict:
    if _sim_mode["enabled"]:
        return sim_risk_manager(state)

    pos = state["positions"]
    balance = state["balance"]
    pv = _portfolio_value(state)
    logs = [_entry("risk_manager: risk metrics calculation")]

    _con = sqlite3.connect(DB_PATH)
    _rows = _con.execute(
        "SELECT lesson FROM agent_memory WHERE agent_name='risk_manager' AND lesson IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT 5"
    ).fetchall()
    _con.close()
    recent_lessons = [r[0] for r in _rows if r[0]]

    # Python-pure calculations
    exposure = (pv - balance) / pv if pv > 0 else 0.0
    danger_ratio = pv / INITIAL_BALANCE
    var_1d = pv * 0.025  # simplified 95% VaR (2.5% daily volatility assumption)

    # Kelly-simplified max allocation
    win_rate_est = 0.55
    avg_win_est = 0.08
    avg_loss_est = 0.05
    kelly_f = (win_rate_est * avg_win_est - (1 - win_rate_est) * avg_loss_est) / avg_win_est
    kelly_alloc = max(0, min(kelly_f * 100, MAX_ALLOC_PCT))

    system = (
        "Tu es un risk manager strict. Ton seul job : évaluer le risque et recommander le sizing. "
        "Tu ne donnes JAMAIS d'opinion sur la direction du marché. "
        "Tu calcules, tu mesures, tu protèges le capital. "
        "Retourne UNIQUEMENT du JSON valide."
    )
    if recent_lessons:
        system += "\nTes erreurs récentes :\n" + "\n".join(
            f"  • {lesson}" for lesson in recent_lessons
        )
    user = (
        f"RISK ASSESSMENT — Cycle #{state['round']}\n\n"
        f"MÉTRIQUES CALCULÉES (Python pur) :\n"
        f"  Portfolio value:    ${pv:.2f}\n"
        f"  Cash:               ${balance:.2f}\n"
        f"  Exposure:           {exposure:.1%}\n"
        f"  Danger ratio:       {danger_ratio:.2f} (mort si < {DEATH_THRESHOLD/INITIAL_BALANCE:.2f})\n"
        f"  VaR 95% 1j:        ${var_1d:.2f}\n"
        f"  Kelly allocation:   {kelly_alloc:.1f}%\n"
        f"  Positions:          {len(pos)}/{MAX_POSITIONS}\n\n"
        f"BRIEF SUPERVISEUR: {state.get('supervisor_brief', '')[:200]}\n\n"
        "Retourne ce JSON uniquement :\n"
        '{\n  "agent": "risk_manager",\n  "risk_score": 5,\n'
        '  "max_safe_allocation_pct": 20.0,\n  "var_1d": 25.0,\n'
        '  "portfolio_exposure_after": 40.0,\n'
        '  "sizing_recommendation": "FULL|HALF|QUARTER|SKIP",\n'
        '  "reasoning": "2 phrases",\n  "warnings": []\n}'
    )

    text = _llm(haiku, HAIKU_ID, [{"role": "user", "content": user}], system=system, max_tokens=400)
    vote = _parse_json_obj(text)
    if not vote:
        vote = {
            "agent": "risk_manager",
            "risk_score": 5,
            "max_safe_allocation_pct": float(kelly_alloc),
            "var_1d": round(var_1d, 2),
            "portfolio_exposure_after": round(exposure * 100, 1),
            "sizing_recommendation": "HALF",
            "reasoning": "Parse error — conservative defaults applied",
            "warnings": ["Parse error"],
        }
    vote["agent"] = "risk_manager"
    vote["agent_name"] = "Risk Manager"
    vote.setdefault("action", "HOLD")
    vote.setdefault("symbol", "")
    vote.setdefault("confidence", 0.5)
    vote.setdefault("allocation_pct", vote.get("max_safe_allocation_pct", MAX_ALLOC_PCT))
    vote.setdefault(
        "signals",
        [
            f"Risk score: {vote.get('risk_score', 5)}/10",
            f"Danger ratio: {danger_ratio:.2f} (death at {DEATH_THRESHOLD/INITIAL_BALANCE:.2f})",
            f"Exposure: {exposure:.0%}",
            f"VaR 95% 1d: ${var_1d:.2f}",
            f"Kelly allocation: {kelly_alloc:.1f}%",
            f"Sizing: {vote.get('sizing_recommendation', 'N/A')}",
        ]
        + vote.get("warnings", []),
    )

    logs.append(
        _entry(
            f"risk_manager: score={vote.get('risk_score',5)}/10 "
            f"sizing={vote.get('sizing_recommendation','?')} "
            f"VaR=${vote.get('var_1d',0):.0f}"
        )
    )
    try:
        _con = sqlite3.connect(DB_PATH)
        _con.execute(
            "INSERT INTO agent_memory (timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source) "
            "VALUES (?,?,?,?,?,NULL,NULL,?)",
            (
                _ts(),
                "risk_manager",
                vote.get("symbol", ""),
                vote.get("action", "HOLD"),
                float(vote.get("confidence", 0.5)),
                "live",
            ),
        )
        _con.commit()
        _con.close()
    except Exception:
        pass
    return {"agent_votes": [vote], "risk_vote": vote, "log": logs}


def macro_watcher_node(state: MultiAgentState) -> dict:
    if _sim_mode["enabled"]:
        return sim_macro_watcher(state)

    sentiment = state.get("sentiment", {})
    pv = _portfolio_value(state)
    pos = state["positions"]
    logs = [_entry("macro_watcher: regime analysis")]

    _con = sqlite3.connect(DB_PATH)
    _rows = _con.execute(
        "SELECT lesson FROM agent_memory WHERE agent_name='macro_watcher' AND lesson IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT 5"
    ).fetchall()
    _con.close()
    recent_lessons = [r[0] for r in _rows if r[0]]

    avg_sent = sum(sentiment.values()) / max(len(sentiment), 1)

    system = (
        "Tu es un macro strategist. Tu analyses le régime de marché global : "
        "VIX implicite, taux, sentiment agrégé, rotation sectorielle. "
        "Tu ignores les actions individuelles. Tu regardes le tableau global. "
        "Retourne UNIQUEMENT du JSON valide."
    )
    if recent_lessons:
        system += "\nTes erreurs récentes :\n" + "\n".join(
            f"  • {lesson}" for lesson in recent_lessons
        )
    user = (
        f"MACRO ANALYSIS — Cycle #{state['round']}\n\n"
        f"PORTFOLIO HEALTH: ${pv:.2f} ({pv/INITIAL_BALANCE:.0%} of initial)\n"
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

    text = _llm(haiku, HAIKU_ID, [{"role": "user", "content": user}], system=system, max_tokens=400)
    vote = _parse_json_obj(text)
    if not vote:
        vote = {
            "agent": "macro_watcher",
            "market_regime": "transitional",
            "macro_bias": "neutral",
            "recommended_exposure": 50,
            "sector_rotation": "balanced",
            "reasoning": "Parse error — neutral stance",
            "macro_score": 0.0,
        }
    vote["agent"] = "macro_watcher"
    vote["agent_name"] = "Macro Watcher"
    vote.setdefault("action", "HOLD")
    vote.setdefault("symbol", "")
    vote.setdefault("confidence", 0.5)
    vote.setdefault("allocation_pct", 0)
    vote.setdefault(
        "signals",
        [
            f"Market regime: {vote.get('market_regime', 'N/A')}",
            f"Macro bias: {vote.get('macro_bias', 'N/A')}",
            f"Portfolio health: {pv/INITIAL_BALANCE:.0%} of initial capital",
            f"Aggregate sentiment: {avg_sent:+.2f}",
            f"Recommended exposure: {vote.get('recommended_exposure', 'N/A')}%",
            f"Sector rotation: {vote.get('sector_rotation', 'N/A')}",
        ],
    )

    logs.append(
        _entry(
            f"macro_watcher: {vote.get('market_regime','?')} {vote.get('macro_bias','?')} "
            f"score={vote.get('macro_score',0):+.2f}"
        )
    )
    try:
        _con = sqlite3.connect(DB_PATH)
        _con.execute(
            "INSERT INTO agent_memory (timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source) "
            "VALUES (?,?,?,?,?,NULL,NULL,?)",
            (
                _ts(),
                "macro_watcher",
                vote.get("symbol", ""),
                vote.get("action", "HOLD"),
                float(vote.get("confidence", 0.5)),
                "live",
            ),
        )
        _con.commit()
        _con.close()
    except Exception:
        pass
    return {"agent_votes": [vote], "macro_vote": vote, "log": logs}


# ═══════════════════════════════════════════════════════════════════════════════
# ARBITRATION NODE
# ═══════════════════════════════════════════════════════════════════════════════


def arbitrate_node(state: MultiAgentState) -> dict:
    votes = state.get("agent_votes", [])
    logs = [_entry(f"arbitrate: {len(votes)} votes received — computing decision")]

    vote_map = {v.get("agent", ""): v for v in votes}
    tech_v = vote_map.get("technician", {})
    ana_v = vote_map.get("analyst", {})
    risk_v = vote_map.get("risk_manager", {})
    macro_v = vote_map.get("macro_watcher", {})

    dynamic_weights = _compute_dynamic_weights(DB_PATH)
    logs.append(_entry(f"arbitrate: weights_used={dynamic_weights}"))

    # Composite action scores (risk_manager & macro_watcher don't vote on direction)
    action_scores: dict[str, float] = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    for v in [tech_v, ana_v]:
        agent = v.get("agent", "")
        weight = dynamic_weights.get(agent, 0.0)
        action = v.get("action", "HOLD")
        conf = float(v.get("confidence", 0.5))
        action_scores[action] = action_scores.get(action, 0.0) + weight * conf

    # Apply HOLD weight for macro + risk as a baseline
    hold_weight = dynamic_weights["risk_manager"] * 0.5 + dynamic_weights["macro_watcher"] * 0.5
    action_scores["HOLD"] += hold_weight * 0.5

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

    votes_summary = json.dumps(
        [{k: vv for k, vv in v.items() if k not in ("key_indicators",)} for v in votes],
        indent=2,
        default=str,
    )

    if _sim_mode["enabled"]:
        emotion = "FOCUSED" if composite_conf > 0.6 else "CALM"
        thoughts = f"[SIM] Composite: {final_action} {symbol}. Score={composite_conf:.2f}. Consensus={consensus}."
        market_intel = macro_v.get("reasoning", "")
        reasoning = (
            f"BUY={action_scores['BUY']:.2f} | SELL={action_scores['SELL']:.2f} | "
            f"HOLD={action_scores['HOLD']:.2f}. Risk {risk_score:.0f}/10. {regime}."
        )
    else:
        system_arb = (
            "Tu es APEX-7, superviseur d'une équipe de 4 traders. "
            "Arbitre leurs votes et justifie la décision finale. "
            "Sois direct et factuel. Retourne UNIQUEMENT du JSON valide."
        )
        user_arb = (
            f"ARBITRATION — Cycle #{state['round']}\n\n"
            f"VOTES:\n{votes_summary}\n\n"
            f"SCORES COMPOSITES:\n"
            f"  BUY={action_scores['BUY']:.3f} | SELL={action_scores['SELL']:.3f} | HOLD={action_scores['HOLD']:.3f}\n\n"
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
        arb = _parse_json_obj(text)
        if not arb:
            arb = {}

        final_action = arb.get("action", final_action)
        symbol = arb.get("symbol", symbol)
        composite_conf = float(arb.get("confidence", composite_conf))
        max_alloc = float(arb.get("allocation_pct", max_alloc))
        reasoning = arb.get("reasoning", "")
        consensus = arb.get("consensus_level", consensus)
        emotion = arb.get("emotion", "CALM")
        thoughts = arb.get("thoughts", "")
        market_intel = arb.get("market_intel", "")
        dissenting = arb.get("dissenting_agents", dissenting)

    arbitration = {
        "action": final_action,
        "symbol": symbol,
        "allocation_pct": min(float(max_alloc), MAX_ALLOC_PCT),
        "confidence": composite_conf,
        "reasoning": (
            reasoning
            if not _sim_mode["enabled"]
            else (
                f"BUY={action_scores['BUY']:.2f} SELL={action_scores['SELL']:.2f} "
                f"HOLD={action_scores['HOLD']:.2f} | Risk {risk_score:.0f}/10 | {regime}"
            )
        ),
        "dissenting_agents": dissenting,
        "consensus_level": consensus,
        "thoughts": thoughts,
        "emotion": emotion,
        "market_intel": market_intel,
        "action_scores": action_scores,
        "_votes": votes,
    }

    decision = {
        "action": final_action,
        "symbol": symbol,
        "allocation_pct": min(float(max_alloc), MAX_ALLOC_PCT),
        "sell_pct": 100,
        "confidence": composite_conf,
        "reasoning": arbitration["reasoning"],
        "thoughts": thoughts,
        "emotion": emotion,
        "market_intel": market_intel,
    }

    skip_res = state.get("skip_research", False) or composite_conf >= 0.72

    # Update was_correct for the agent_memory rows just inserted this cycle
    try:
        _con = sqlite3.connect(DB_PATH)
        for _agent_name in ["technician", "analyst", "risk_manager", "macro_watcher"]:
            _av = vote_map.get(_agent_name, {})
            _correct = 1 if _av.get("action", "HOLD") == final_action else 0
            _con.execute(
                "UPDATE agent_memory SET was_correct=? WHERE id=("
                "SELECT id FROM agent_memory WHERE agent_name=? AND was_correct IS NULL "
                "ORDER BY timestamp DESC LIMIT 1)",
                (_correct, _agent_name),
            )
        _con.commit()
        _con.close()
    except Exception as _e:
        logs.append(_entry(f"arbitrate: agent_memory update error: {_e}", "warning"))

    logs.append(
        _entry(
            f"arbitrate: {final_action} {symbol} conf={composite_conf:.0%} "
            f"consensus={consensus} dissenting={dissenting}"
        )
    )
    if thoughts:
        logs.append(_entry(f"thoughts: {thoughts[:120]}"))

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
# DAILY POSTMORTEM
# ═══════════════════════════════════════════════════════════════════════════════


def run_daily_postmortem(portfolio: Portfolio, db_path=DB_PATH) -> None:
    """Generate postmortem entries for all SELL trades since midnight."""
    midnight = datetime.combine(date.today(), datetime.min.time()).isoformat()
    source = "simulation" if _sim_mode["enabled"] else "live"

    sells = portfolio.closed_trades_since(midnight)
    if not sells:
        return

    con = sqlite3.connect(db_path)
    for trade in sells:
        symbol = trade["symbol"]
        sell_price = trade["price"]
        sell_time = datetime.fromisoformat(trade["time"])

        # Find the most recent matching BUY in trade_history
        buy_trade = next(
            (
                t
                for t in reversed(portfolio.trade_history)
                if t["action"] == "BUY" and t["symbol"] == symbol
            ),
            None,
        )
        if not buy_trade:
            continue

        buy_price = buy_trade["price"]
        buy_time = datetime.fromisoformat(buy_trade["time"])
        holding_hours = (sell_time - buy_time).total_seconds() / 3600
        pnl_pct = ((sell_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0

        rows = con.execute(
            "SELECT agent_name FROM agent_memory "
            "WHERE symbol=? AND was_correct=1 AND vote='SELL' "
            "ORDER BY timestamp DESC LIMIT 4",
            (symbol,),
        ).fetchall()
        agents_correct = json.dumps([r[0] for r in rows])

        if _sim_mode["enabled"]:
            summary = f"[SIM] P&L {pnl_pct:+.2f}% sur {holding_hours:.1f}h — signal RSI."
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

        con.execute(
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

    con.commit()
    con.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════════════════════


def _route_arbitrate(state: MultiAgentState) -> str:
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
    g.add_node("skip", skip_node)
    g.add_node("research", research_node)

    # Multi-agent specific nodes
    g.add_node("supervisor", supervisor_node)
    g.add_node("technician", technician_node)
    g.add_node("analyst", analyst_node)
    g.add_node("risk_manager", risk_manager_node)
    g.add_node("macro_watcher", macro_watcher_node)
    g.add_node("arbitrate", arbitrate_node)

    # Edges: linear start
    g.add_edge(START, "load_memory")
    g.add_edge("load_memory", "fetch_data")
    g.add_edge("fetch_data", "supervisor")

    # Fan-out from supervisor to 4 parallel agents
    g.add_conditional_edges(
        "supervisor",
        _route_to_agents,
        ["technician", "analyst", "risk_manager", "macro_watcher"],
    )

    # Fan-in: all 4 parallel agents → arbitrate
    g.add_edge("technician", "arbitrate")
    g.add_edge("analyst", "arbitrate")
    g.add_edge("risk_manager", "arbitrate")
    g.add_edge("macro_watcher", "arbitrate")

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
agent_multi_graph = build_multi_graph(Portfolio())
