"""
APEX-7 — Agent LangGraph v2

Graph:
  __start__
      │
  load_memory  (haiku)
      │
  fetch_data   (async parallel — no LLM)
      │
  analyze      (sonnet + web_search)
      │
  ┌───┴───┐
  │       │
conf≥0.7  conf<0.7
  │       │
  │    research  (sonnet + web_search, max 2×)
  │       │
  └───┬───┘
      │
  risk_check   (pure Python rules)
      │
  ┌───┴───┐
  │       │
exec    skip
  │
save_memory  (haiku)
  │
__end__
"""

import asyncio
import json
import operator
import random
import re
import sqlite3
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Annotated, List, Optional, TypedDict

import anthropic
import yfinance as yf
from langgraph.graph import END, START, StateGraph

try:
    import tweepy
    _HAS_TWEEPY = True
except ImportError:
    _HAS_TWEEPY = False

from config import (
    AGENT_INTERVAL,
    ANTHROPIC_API_KEY,
    DEATH_THRESHOLD,
    INITIAL_BALANCE,
    MAX_ALLOC_PCT,
    MAX_POSITIONS,
    SIMULATION_MODE,
    SIM_DRIFT,
    SIM_VOLATILITY,
    STOP_LOSS_PCT,
    WATCHLIST,
    X_BEARER_TOKEN,
)
from data import Portfolio

# ── Models ───────────────────────────────────────────────────────────────────

SONNET_ID = "claude-sonnet-4-5"
HAIKU_ID  = "claude-haiku-4-5-20251001"

sonnet = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
haiku  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Runtime simulation toggle (survives hot-switch from Dash UI)
_sim_mode: dict = {"enabled": SIMULATION_MODE}

# ── SQLite ───────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent / "trades.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp             TEXT,
    symbol                TEXT,
    action                TEXT,
    price                 REAL,
    amount_usd            REAL,
    shares                REAL,
    reasoning             TEXT,
    confidence            REAL,
    emotion               TEXT,
    portfolio_value_after REAL,
    lesson                TEXT,
    source                TEXT DEFAULT 'live'
);
CREATE TABLE IF NOT EXISTS patterns (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    pattern   TEXT
);
CREATE TABLE IF NOT EXISTS agent_memory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT,
    agent_name   TEXT,
    symbol       TEXT,
    vote         TEXT,
    confidence   REAL,
    was_correct  INTEGER,
    lesson       TEXT,
    source       TEXT DEFAULT 'simulation'
);
CREATE TABLE IF NOT EXISTS postmortem (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT,
    symbol          TEXT,
    buy_price       REAL,
    sell_price      REAL,
    pnl_pct         REAL,
    holding_hours   REAL,
    agents_correct  TEXT,
    summary         TEXT,
    source          TEXT DEFAULT 'simulation'
);
"""


def _init_db() -> None:
    con = sqlite3.connect(DB_PATH)
    con.executescript(_SCHEMA)
    # Soft migration: add source column if missing (idempotent)
    try:
        con.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'live'")
        con.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    con.close()


_init_db()

# ── State ────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    # Portfolio
    balance:           float
    positions:         dict                          # {symbol: {shares, avg_price}}
    portfolio_history: Annotated[List[float], operator.add]

    # Market data
    prices:    dict                                  # {symbol: float}
    news:      str
    sentiment: dict                                  # {symbol: float -1..1}

    # Memory
    past_trades:    List[dict]
    known_patterns: List[str]

    # Agent
    round:               int
    confidence:          float
    research_iterations: int
    decision:            Optional[dict]
    emotion:             str
    thoughts:            str

    # Logs
    log: Annotated[List[dict], operator.add]

    # Control
    alive:         bool
    skip_research: bool


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


def _llm(
    client: anthropic.Anthropic,
    model: str,
    messages: list,
    system: str = "",
    max_tokens: int = 1024,
    web_search: bool = False,
) -> str:
    """Single LLM call or agentic web-search loop. Returns assistant text."""
    tools = [{"type": "web_search_20250305", "name": "web_search"}] if web_search else []
    msgs = list(messages)
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": msgs}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    resp = None
    for _ in range(8):
        resp = client.messages.create(**kwargs)
        if resp.stop_reason == "end_turn" or not tools:
            break
        if resp.stop_reason == "tool_use":
            msgs = msgs + [{"role": "assistant", "content": resp.content}]
            results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": ""}
                for b in resp.content
                if b.type == "tool_use"
            ]
            msgs = msgs + [{"role": "user", "content": results}]
            kwargs["messages"] = msgs
        else:
            break

    if resp is None:
        return ""
    return next((b.text for b in resp.content if hasattr(b, "text") and b.text), "")


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
                title = (item.get("title")
                         or (item.get("content") or {}).get("title", ""))
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


async def _gather_data(
    portfolio: Portfolio, news_syms: list[str]
) -> tuple[dict, str, dict]:
    loop = asyncio.get_event_loop()
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


def _portfolio_value(state: AgentState) -> float:
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
    "BUY":  "RSI oversold, risk/reward favorable. Entering position with discipline.",
    "SELL": "RSI overbought, locking in gains before reversal. Cash is a position.",
    "HOLD": "No clear edge. Preserving capital until setup aligns.",
}

# Per-symbol simulated price history (for RSI computation)
_sim_price_history: dict[str, list[float]] = {}


def _sim_rsi(prices_hist: list[float], period: int = 14) -> float:
    """Compute RSI from a list of prices. Returns 50.0 if not enough data."""
    if len(prices_hist) < period + 1:
        return 50.0
    deltas = [prices_hist[i + 1] - prices_hist[i] for i in range(-period - 1, -1)]
    gains  = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_g  = sum(gains)  / period if gains  else 0.0
    avg_l  = sum(losses) / period if losses else 0.0
    if avg_l == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_g / avg_l))


def _sim_step_prices(current: dict[str, float]) -> dict[str, float]:
    """Random-walk one step for each symbol."""
    drift = _sim_mode.get("drift", SIM_DRIFT)
    vol   = _sim_mode.get("volatility", SIM_VOLATILITY)
    new_prices: dict[str, float] = {}
    for sym, price in current.items():
        change = random.gauss(drift, vol)
        new_prices[sym] = max(price * (1 + change), 0.01)
        _sim_price_history.setdefault(sym, [price]).append(new_prices[sym])
        if len(_sim_price_history[sym]) > 100:        # keep last 100
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

    prices    = _sim_step_prices(current)
    news_syms = list(state["positions"].keys())[:3] or WATCHLIST[:3]
    news      = "\n".join(
        random.choice(_SIM_NEWS_TEMPLATES).format(sym=s) for s in news_syms
    )
    sentiment = {s: round(random.uniform(-1, 1), 2) for s in WATCHLIST}

    # Update portfolio's cached prices so execute_node has values
    with portfolio._lock:
        portfolio.last_prices = prices

    flat = _is_flat(prices)
    _prev_prices.update(prices)
    logs.append(_entry(f"[SIM] prices={prices} | flat={flat}"))

    return {
        "prices":        prices,
        "news":          news,
        "sentiment":     sentiment,
        "skip_research": flat,
        "log":           logs,
    }


def sim_analyze(state: AgentState) -> dict:
    """Rule-based analyzer — no LLM, uses simulated RSI."""
    logs = [_entry(f"[SIM] analyze: round={state['round']}")]

    prices = state["prices"]
    pv     = _portfolio_value(state)

    # Compute RSI per symbol and pick best candidate
    rsi_map: dict[str, float] = {
        sym: _sim_rsi(_sim_price_history.get(sym, [prices[sym]]))
        for sym in WATCHLIST if sym in prices
    }
    logs.append(_entry(f"[SIM] RSI: {rsi_map}"))

    # Choose action
    oversold  = {s: r for s, r in rsi_map.items() if r < 30}
    overbought = {s: r for s, r in rsi_map.items()
                  if r > 70 and s in state["positions"]}

    if overbought:
        sym    = min(overbought, key=overbought.get)  # most overbought held pos
        action = "SELL"
        conf   = 0.75
        alloc  = 0
        sell_p = 100
        rsi_v  = rsi_map[sym]
    elif oversold and len(state["positions"]) < MAX_POSITIONS:
        sym    = min(oversold, key=oversold.get)       # most oversold on watchlist
        action = "BUY"
        conf   = 0.80
        alloc  = random.randint(15, MAX_ALLOC_PCT)
        sell_p = 0
        rsi_v  = rsi_map[sym]
    else:
        sym    = random.choice(WATCHLIST) if WATCHLIST else ""
        action = "HOLD"
        conf   = 0.55
        alloc  = 0
        sell_p = 0
        rsi_v  = rsi_map.get(sym, 50.0)

    # Emotion from portfolio value
    if pv < INITIAL_BALANCE * 0.7:
        emotion = "PANIC"
    elif pv < INITIAL_BALANCE * 0.9:
        emotion = "NERVOUS"
    elif pv > INITIAL_BALANCE * 1.3:
        emotion = "EUPHORIC"
    else:
        emotion = random.choice(["CALM", "FOCUSED", "EXCITED"])

    thoughts = _SIM_THOUGHTS.get(action, "Analyzing market conditions.")
    reasoning = (
        f"RSI={rsi_v:.1f} → {action}. "
        f"Portfolio ${pv:.2f} | {emotion}"
    )

    decision = {
        "thoughts":      thoughts,
        "emotion":       emotion,
        "action":        action,
        "symbol":        sym,
        "allocation_pct": alloc,
        "sell_pct":      sell_p,
        "reasoning":     reasoning,
        "confidence":    conf,
        "market_intel":  f"Simulated RSI={rsi_v:.1f}",
    }

    skip = state["skip_research"] or (not state["positions"] and conf >= 0.60)
    logs.append(_entry(
        f"[SIM] {action} {sym} conf={conf:.0%} emotion={emotion} RSI={rsi_v:.1f}"
    ))

    return {
        "decision":      decision,
        "confidence":    conf,
        "emotion":       emotion,
        "thoughts":      thoughts,
        "skip_research": skip,
        "log":           logs,
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


# ── .env writer (for Dash mode toggle) ───────────────────────────────────────

def _write_env_var(key: str, value: str) -> None:
    env_path = Path(__file__).parent / ".env"
    try:
        lines = env_path.read_text().splitlines()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}")
        env_path.write_text("\n".join(lines) + "\n")
    except Exception:
        pass


def set_simulation_mode(enabled: bool) -> None:
    _sim_mode["enabled"] = enabled
    _write_env_var("SIMULATION_MODE", "true" if enabled else "false")


def get_simulation_mode() -> bool:
    return _sim_mode["enabled"]


# ═══════════════════════════════════════════════════════════════════════════════
# NODES
# ═══════════════════════════════════════════════════════════════════════════════

def load_memory_node(state: AgentState) -> dict:
    logs = [_entry("load_memory: querying SQLite...")]

    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT timestamp,symbol,action,price,amount_usd,shares,"
        "reasoning,confidence,emotion,portfolio_value_after,lesson "
        "FROM trades ORDER BY timestamp DESC LIMIT 20"
    ).fetchall()
    con.close()

    cols = ("timestamp", "symbol", "action", "price", "amount_usd", "shares",
            "reasoning", "confidence", "emotion", "portfolio_value_after", "lesson")
    past_trades = [dict(zip(cols, row)) for row in rows]

    if not past_trades:
        logs.append(_entry("load_memory: no history yet"))
        return {"past_trades": [], "known_patterns": [], "log": logs}

    # In simulation mode, skip the LLM pattern extraction
    if _sim_mode["enabled"]:
        patterns = [t["lesson"] for t in past_trades if t.get("lesson")][:5]
        logs.append(_entry(f"[SIM] load_memory: {len(past_trades)} trades (no LLM analysis)"))
        return {"past_trades": past_trades, "known_patterns": patterns, "log": logs}

    prompt = (
        "Analyse ces trades récents et identifie les patterns, erreurs répétées, ou succès :\n"
        f"{json.dumps(past_trades[:10], indent=2, default=str)}\n\n"
        "Retourne UNIQUEMENT un JSON array de strings, chaque string décrit un pattern "
        "(max 15 mots). Exemple : [\"Achète AAPL trop tôt après correction\", ...]"
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
            sorted(pos, key=lambda s: pos[s]["shares"] * state["prices"].get(s, 0),
                   reverse=True)[:3]
            if pos else WATCHLIST[:3]
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

        logs.append(_entry(
            f"fetch_data: {len(prices)} prices | news={len(news)}ch | "
            f"sentiment={sentiment} | flat={flat}"
        ))
        return {
            "prices": prices,
            "news": news,
            "sentiment": sentiment,
            "skip_research": flat,
            "log": logs,
        }
    return fetch_data_node


def analyze_node(state: AgentState) -> dict:
    if _sim_mode["enabled"]:
        return sim_analyze(state)

    it = state["research_iterations"]
    logs = [_entry(f"analyze: round={state['round']} research_iter={it}")]

    pv = _portfolio_value(state)
    mode = ("PANIC" if pv < INITIAL_BALANCE * 0.5
            else "GREED" if pv > INITIAL_BALANCE * 1.5
            else "NORMAL")

    positions_display = {
        sym: {
            "shares":   round(pos["shares"], 4),
            "avg_price": round(pos.get("avg_price", pos.get("avg_cost", 0)), 2),
            "now":       round(state["prices"].get(sym, 0), 2),
            "pnl%":     round(
                ((state["prices"].get(sym, 1) /
                  max(pos.get("avg_price", pos.get("avg_cost", 1)), 0.01)) - 1) * 100, 2
            ),
        }
        for sym, pos in state["positions"].items()
    }
    patterns_txt = (
        "\n".join(f"  • {p}" for p in state["known_patterns"])
        or "  Aucun pattern enregistré"
    )

    system = (
        "Tu es APEX-7, un trading agent IA en survival mode. "
        f"Budget initial : ${INITIAL_BALANCE}. Tu meurs si portfolio < ${DEATH_THRESHOLD}. "
        "Personnalité : trader Wall Street, brutal, factuel, sans sentiment. "
        "Utilise web_search pour collecter de l'intel avant de décider. "
        "Retourne UNIQUEMENT du JSON valide, rien avant ni après."
    )
    user = f"""CYCLE #{state['round']} | MODE : {mode} | RESEARCH ITER : {it}

PORTFOLIO
  Cash       : ${state['balance']:.2f}
  Total Value: ${pv:.2f}
  Positions  : {json.dumps(positions_display, indent=4)}

WATCHLIST PRIX
{json.dumps({s: f"${p:.2f}" for s, p in state['prices'].items()}, indent=2)}

NEWS
{state['news'] or 'Aucune news'}

SENTIMENT  (-1=baissier → +1=haussier)
{json.dumps(state['sentiment'], indent=2)}

MÉMOIRE — PATTERNS CONNUS
{patterns_txt}

DERNIERS TRADES
{json.dumps(state['past_trades'][:5], indent=2, default=str)}

Retourne ce JSON (et RIEN d'autre) :
{{
  "thoughts":     "monologue interne 2-3 phrases",
  "emotion":      "CALM|FOCUSED|EXCITED|NERVOUS|PANIC|EUPHORIC|DESPERATE",
  "action":       "BUY|SELL|HOLD",
  "symbol":       "TICKER ou null",
  "allocation_pct": 10,
  "sell_pct":     100,
  "reasoning":    "thèse en 1-2 phrases",
  "confidence":   0.75,
  "market_intel": "insight clé issu de la recherche"
}}"""

    text = _llm(sonnet, SONNET_ID,
                [{"role": "user", "content": user}],
                system=system, max_tokens=1024, web_search=True)

    decision  = _parse_json_obj(text)
    confidence = float(decision.get("confidence", 0.5))
    emotion    = decision.get("emotion", "CALM")
    thoughts   = decision.get("thoughts", "")

    # skip_research: no positions + conf ok, or flat market (already set in fetch_data)
    skip = state["skip_research"] or (not state["positions"] and confidence >= 0.60)

    logs.append(_entry(
        f"analyze: {decision.get('action')} {decision.get('symbol') or ''} "
        f"conf={confidence:.0%} emotion={emotion} skip_research={skip}"
    ))
    if thoughts:
        logs.append(_entry(f"thoughts: {thoughts[:140]}"))

    return {
        "decision":      decision,
        "confidence":    confidence,
        "emotion":       emotion,
        "thoughts":      thoughts,
        "skip_research": skip,
        "log":           logs,
    }


def research_node(state: AgentState) -> dict:
    if _sim_mode["enabled"]:
        return sim_research(state)

    decision  = state.get("decision") or {}
    symbol    = decision.get("symbol") or ""
    reasoning = decision.get("reasoning") or ""
    it        = state["research_iterations"] + 1
    logs      = [_entry(f"research #{it}: deep-dive on {symbol}")]

    prompt = (
        f"Recherche approfondie sur : {symbol} — {reasoning}\n\n"
        "Fournis en 5-6 phrases : catalyseurs récents, risques, sentiment marché, "
        "niveau technique clé (support/résistance), consensus analystes si dispo. "
        "Sois factuel et concis."
    )
    text = _llm(sonnet, SONNET_ID,
                [{"role": "user", "content": prompt}],
                max_tokens=2048, web_search=True)

    logs.append(_entry(f"research #{it}: {len(text)} chars gathered for {symbol}"))
    return {
        "news":                state["news"] + f"\n\n─── RESEARCH #{it} [{symbol}] ───\n{text}",
        "research_iterations": it,
        "log":                 logs,
    }


def risk_check_node(state: AgentState) -> dict:
    decision = state.get("decision") or {}
    action   = decision.get("action", "HOLD").upper()
    symbol   = decision.get("symbol") or ""
    alloc    = float(decision.get("allocation_pct", 10))
    sell_pct = float(decision.get("sell_pct", 100))
    prices   = state["prices"]
    pos      = state["positions"]
    balance  = state["balance"]
    pv       = _portfolio_value(state)

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

    logs = [_entry(
        f"risk_check: {'✓ PASS' if passed else '✗ FAIL — ' + reason}",
        level="info" if passed else "warning",
    )]
    return {
        "decision": {**decision, "_risk_passed": passed, "_risk_reason": reason},
        "log": logs,
    }


def make_execute_node(portfolio: Portfolio):
    def execute_node(state: AgentState) -> dict:
        decision = state.get("decision") or {}
        action   = decision.get("action", "HOLD").upper()
        symbol   = decision.get("symbol") or ""
        alloc    = float(decision.get("allocation_pct", 10))
        sell_pct = float(decision.get("sell_pct", 100))
        prices   = state["prices"]
        pv       = portfolio.total_value(prices)
        logs     = [_entry(f"execute: {action} {symbol}")]

        result: dict = {"success": False, "error": "no-op"}

        # Stop-loss check on all open positions before executing the agent decision
        for sl_sym, sl_pos in list(portfolio.positions.items()):
            sl_price = prices.get(sl_sym, 0.0)
            sl_avg = sl_pos.get("avg_price", sl_pos.get("avg_cost", 0))
            if sl_avg > 0 and sl_price > 0:
                sl_pct = (sl_price - sl_avg) / sl_avg
                if sl_pct < -STOP_LOSS_PCT:
                    sl_slip = 1 + random.uniform(-0.001, 0.001)
                    portfolio.sell(sl_sym, 100, sl_price * sl_slip)
                    logs.append(_entry(
                        f"STOP-LOSS triggered: {sl_sym} @ ${sl_price:.2f} (loss: {sl_pct:.1%})",
                        "warning",
                    ))

        if action == "BUY" and symbol in prices:
            slip  = 1 + random.uniform(-0.001, 0.001)
            price = prices[symbol] * slip
            amount = pv * (min(alloc, MAX_ALLOC_PCT) / 100)
            result = portfolio.buy(symbol, amount, price)
            if result["success"]:
                logs.append(_entry(
                    f"BUY {symbol} {result['shares']:.5f} sh @ ${price:.2f} "
                    f"= ${result['amount']:.2f}  slip={slip-1:+.3%}"
                ))
                portfolio.save_state(DB_PATH.parent / ".apex7_state.json")

        elif action == "SELL" and symbol:
            slip  = 1 + random.uniform(-0.001, 0.001)
            price = prices.get(symbol, 0) * slip
            result = portfolio.sell(symbol, sell_pct, price)
            if result["success"]:
                logs.append(_entry(
                    f"SELL {symbol} {sell_pct:.0f}% @ ${price:.2f} "
                    f"= ${result['amount']:.2f}  slip={slip-1:+.3%}"
                ))
                portfolio.save_state(DB_PATH.parent / ".apex7_state.json")

        elif action == "HOLD":
            logs.append(_entry(f"HOLD — {decision.get('reasoning','')[:100]}"))
            result = {"success": True}

        if not result.get("success"):
            logs.append(_entry(f"execute failed: {result.get('error', '?')}", "warning"))

        portfolio.record_value(prices)
        portfolio.check_death(prices)
        new_pv = portfolio.total_value(prices)

        return {
            "balance":           portfolio.cash,
            "positions":         dict(portfolio.positions),
            "portfolio_history": [new_pv],
            "alive":             not portfolio.is_dead,
            "log":               logs,
        }
    return execute_node


def make_save_memory_node(portfolio: Portfolio):
    def save_memory_node(state: AgentState) -> dict:
        decision = state.get("decision") or {}
        action   = decision.get("action", "HOLD").upper()
        logs     = [_entry("save_memory: persisting...")]

        if action == "HOLD":
            logs.append(_entry("save_memory: HOLD — skipped"))
            return {"log": logs}

        symbol = decision.get("symbol") or ""
        prices = state["prices"]
        price  = prices.get(symbol, 0.0)
        pv_after = portfolio.total_value(prices)

        last_trade = next(
            (t for t in reversed(portfolio.trade_history) if t.get("symbol") == symbol),
            {}
        )
        shares = last_trade.get("shares", 0.0)
        amount = last_trade.get("amount", 0.0)

        source = "simulation" if _sim_mode["enabled"] else "live"

        if _sim_mode["enabled"]:
            lesson = f"[SIM] {action} {symbol} @ ${price:.2f} — RSI-based signal"
        else:
            lesson_prompt = (
                f"En une phrase concise (max 15 mots), quelle leçon retenir de ce trade ?\n"
                f"Action: {action} {symbol} @ ${price:.2f} | "
                f"Conf: {decision.get('confidence', 0):.0%} | "
                f"Émotion: {state['emotion']} | "
                f"Portfolio après: ${pv_after:.2f}"
            )
            lesson = _llm(haiku, HAIKU_ID,
                          [{"role": "user", "content": lesson_prompt}],
                          max_tokens=80).strip()

        try:
            con = sqlite3.connect(DB_PATH)
            con.execute(
                "INSERT INTO trades "
                "(timestamp,symbol,action,price,amount_usd,shares,"
                "reasoning,confidence,emotion,portfolio_value_after,lesson,source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _ts(), symbol, action, price, amount, shares,
                    decision.get("reasoning", ""),
                    float(decision.get("confidence", 0.0)),
                    state["emotion"],
                    pv_after,
                    lesson,
                    source,
                ),
            )
            con.execute(
                "INSERT INTO patterns (timestamp, pattern) VALUES (?,?)",
                (_ts(), lesson),
            )
            con.commit()
            con.close()
        except Exception as e:
            logs.append(_entry(f"save_memory DB error: {e}", "error"))

        logs.append(_entry(f"save_memory: lesson → {lesson[:90]}"))
        return {
            "known_patterns": state["known_patterns"] + [lesson],
            "log": logs,
        }
    return save_memory_node


def skip_node(state: AgentState) -> dict:
    decision = state.get("decision") or {}
    reason   = decision.get("_risk_reason") or "trade rejected by risk_check"
    return {"log": [_entry(f"skip: {reason}", "warning")]}


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════════════════════

def _route_analyze(state: AgentState) -> str:
    if (state.get("skip_research")
            or state["confidence"] >= 0.70
            or state["research_iterations"] >= 2):
        return "risk_check"
    return "research"


def _route_risk(state: AgentState) -> str:
    return "execute" if (state.get("decision") or {}).get("_risk_passed", True) else "skip"


# ═══════════════════════════════════════════════════════════════════════════════
# GRAPH
# ═══════════════════════════════════════════════════════════════════════════════

def build_graph(portfolio: Portfolio | None = None):
    if portfolio is None:
        portfolio = Portfolio()
    g = StateGraph(AgentState)

    g.add_node("load_memory", load_memory_node)
    g.add_node("fetch_data",  make_fetch_data_node(portfolio))
    g.add_node("analyze",     analyze_node)
    g.add_node("research",    research_node)
    g.add_node("risk_check",  risk_check_node)
    g.add_node("execute",     make_execute_node(portfolio))
    g.add_node("save_memory", make_save_memory_node(portfolio))
    g.add_node("skip",        skip_node)

    g.add_edge(START,         "load_memory")
    g.add_edge("load_memory", "fetch_data")
    g.add_edge("fetch_data",  "analyze")

    g.add_conditional_edges(
        "analyze", _route_analyze,
        {"risk_check": "risk_check", "research": "research"},
    )
    g.add_edge("research", "analyze")   # loop: research feeds back into analyze

    g.add_conditional_edges(
        "risk_check", _route_risk,
        {"execute": "execute", "skip": "skip"},
    )
    g.add_edge("execute",     "save_memory")
    g.add_edge("save_memory", END)
    g.add_edge("skip",        END)

    return g.compile()


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT STATUS  (read by Dash)
# ═══════════════════════════════════════════════════════════════════════════════

_agent_status: dict = {
    "cycle":               0,
    "emotion":             "CALM",
    "thoughts":            "",
    "confidence":          0.0,
    "decision":            None,
    "research_iterations": 0,
    "alive":               True,
    "last_update":         None,
}


def get_agent_status() -> dict:
    return dict(_agent_status)


# ═══════════════════════════════════════════════════════════════════════════════
# THREAD ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def start_agent(portfolio: Portfolio) -> threading.Thread:
    """Unused from dashboard. For standalone use only. See app.py _agent_loop."""
    graph = build_graph(portfolio)

    def _loop() -> None:
        cycle = 0
        while not portfolio.is_dead:
            cycle += 1
            portfolio.log(f"=== CYCLE {cycle} START ===")
            try:
                initial: AgentState = {
                    "balance":             portfolio.cash,
                    "positions":           dict(portfolio.positions),
                    "portfolio_history":   [],
                    "prices":              dict(portfolio.last_prices),
                    "news":                "",
                    "sentiment":           {},
                    "past_trades":         [],
                    "known_patterns":      [],
                    "round":               cycle,
                    "confidence":          0.0,
                    "research_iterations": 0,
                    "decision":            None,
                    "emotion":             "CALM",
                    "thoughts":            "",
                    "log":                 [],
                    "alive":               True,
                    "skip_research":       False,
                }
                result = graph.invoke(initial)

                _agent_status.update({
                    "cycle":               cycle,
                    "emotion":             result.get("emotion", "CALM"),
                    "thoughts":            result.get("thoughts", ""),
                    "confidence":          result.get("confidence", 0.0),
                    "decision":            result.get("decision"),
                    "research_iterations": result.get("research_iterations", 0),
                    "alive":               result.get("alive", True),
                    "last_update":         _ts(),
                })

                # Forward structured log to portfolio (for Dash)
                for entry in result.get("log", []):
                    portfolio.log(entry["message"], entry.get("level", "info"))

                if not result.get("alive", True):
                    portfolio.is_dead = True
                    portfolio.log("DEATH CONDITION MET", "critical")
                    break

            except Exception as e:
                portfolio.log(f"Agent cycle error: {e}", "error")
                portfolio.log(traceback.format_exc(), "error")

            sleep_s = 3 if _sim_mode["enabled"] else AGENT_INTERVAL
            portfolio.log(f"=== CYCLE {cycle} DONE — sleeping {sleep_s}s ===")
            time.sleep(sleep_s)

    t = threading.Thread(target=_loop, daemon=True, name="apex7-agent")
    t.start()
    return t


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("=" * 64)
    print("  APEX-7  AGENT v2 — Standalone Test")
    print("=" * 64)

    p = Portfolio()
    print(f"  Portfolio : ${p.cash:.2f} cash | {len(p.positions)} positions")
    print(f"  Watchlist : {WATCHLIST}")
    print(f"  DB        : {DB_PATH}")
    print()

    graph = build_graph(p)

    state: AgentState = {
        "balance":             p.cash,
        "positions":           {},
        "portfolio_history":   [],
        "prices":              {},
        "news":                "",
        "sentiment":           {},
        "past_trades":         [],
        "known_patterns":      [],
        "round":               1,
        "confidence":          0.0,
        "research_iterations": 0,
        "decision":            None,
        "emotion":             "CALM",
        "thoughts":            "",
        "log":                 [],
        "alive":               True,
        "skip_research":       False,
    }

    print("Running one full cycle  (calls Anthropic + yfinance)...")
    print("-" * 64)

    try:
        result = graph.invoke(state)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except Exception as exc:
        print(f"\nFATAL: {exc}")
        traceback.print_exc()
        sys.exit(1)

    print()
    print("=" * 64)
    print("  RESULT")
    print("=" * 64)
    dec = result.get("decision") or {}
    print(f"  Emotion     : {result.get('emotion')}")
    print(f"  Confidence  : {result.get('confidence', 0):.0%}")
    print(f"  Research    : {result.get('research_iterations', 0)} iteration(s)")
    print(f"  Action      : {dec.get('action')} {dec.get('symbol') or ''}")
    print(f"  Allocation  : {dec.get('allocation_pct', 0)}%")
    print(f"  Reasoning   : {(dec.get('reasoning') or '')[:100]}")
    print(f"  Thoughts    : {(result.get('thoughts') or '')[:120]}")
    print(f"  Intel       : {(dec.get('market_intel') or '')[:100]}")
    print(f"  Alive       : {result.get('alive', True)}")
    print()
    print(f"  Portfolio after :")
    print(f"    Cash       ${p.cash:.2f}")
    print(f"    Positions  {dict(p.positions)}")
    print(f"    Total      ${p.total_value():.2f}")
    print()
    log = result.get("log", [])
    print(f"  Log ({len(log)} entries):")
    for e in log:
        lvl = e.get("level", "info").upper()
        t = e["time"][11:19]
        print(f"    [{t}] [{lvl:8s}] {e['message'][:90]}")

# LangGraph Studio compatibility — module-level compiled graph
from data import Portfolio as _Portfolio
agent_graph = build_graph(_Portfolio())

