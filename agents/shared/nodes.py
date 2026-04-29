"""agents.shared.nodes — shared helpers, nodes, DB, sim engine extracted from agent.py."""

import asyncio
import json
import logging
import random
import re
import sqlite3
import threading
import time
import uuid as _uuid_mod
from contextlib import closing
from datetime import datetime, date
from pathlib import Path

import anthropic
import httpx
import yfinance as yf

try:
    import tweepy

    _HAS_TWEEPY = True
except ImportError:
    _HAS_TWEEPY = False

from config import (
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
from core.data import Portfolio
from agents.shared.state import AgentState
from core.indicators import rsi as _rsi
from agents.shared.schemas import validate_decision

logger = logging.getLogger("apex7")

# ── Models ───────────────────────────────────────────────────────────────────

SONNET_ID = "claude-sonnet-4-5"
HAIKU_ID = "claude-haiku-4-5-20251001"

_API_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
sonnet = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=_API_TIMEOUT)
haiku = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=_API_TIMEOUT)

# Runtime simulation toggle (survives hot-switch from Dash UI)
_sim_mode: dict = {"enabled": SIMULATION_MODE}

# ── SQLite ───────────────────────────────────────────────────────────────────

_DB_ROOT = Path(__file__).parent.parent.parent
DB_PATH = _DB_ROOT / "trades.db"  # kept for backward compat


def _get_db_path() -> Path:
    """Return the DB path based on current simulation mode."""
    if _sim_mode["enabled"]:
        return _DB_ROOT / "trades_sim.db"
    return _DB_ROOT / "trades.db"


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


_db_init_lock = threading.Lock()
_db_initialized = False


def _init_db() -> None:
    """Create tables and set WAL mode for both live and sim databases."""
    for db_file in [_DB_ROOT / "trades.db", _DB_ROOT / "trades_sim.db"]:
        with closing(sqlite3.connect(db_file)) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA busy_timeout=5000")
            con.executescript(_SCHEMA)
            try:
                con.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'live'")
                con.commit()
            except sqlite3.OperationalError:
                pass


def _ensure_db() -> None:
    """Lazy DB initialisation — called on first write/read, not at import time."""
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        _init_db()
        _db_initialized = True


def _db_write(query: str, params: tuple, *, retries: int = 3) -> bool:
    """Centralized SQLite write with retries and logging.

    WAL mode is set once by ``_init_db()`` — no need to repeat per-write.
    """
    _ensure_db()
    for attempt in range(retries):
        try:
            with closing(sqlite3.connect(_get_db_path(), timeout=5)) as con:
                con.execute(query, params)
                con.commit()
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            logger.error("SQLite write failed: %s (query=%s)", e, query[:80])
            return False
        except Exception as e:
            logger.error("SQLite unexpected error: %s", e)
            return False
    return False


def _db_write_multi(queries: list[tuple[str, tuple]], *, retries: int = 3) -> bool:
    """Write multiple queries in a single transaction."""
    _ensure_db()
    for attempt in range(retries):
        try:
            with closing(sqlite3.connect(_get_db_path(), timeout=5)) as con:
                for query, params in queries:
                    con.execute(query, params)
                con.commit()
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            logger.error("SQLite multi-write failed: %s", e)
            return False
        except Exception as e:
            logger.error("SQLite unexpected error: %s", e)
            return False
    return False


def _db_read(query: str, params: tuple = (), *, retries: int = 3) -> list:
    """Centralized SQLite read — sim/live path, WAL from ``_init_db``, busy_timeout, retries."""
    _ensure_db()
    for attempt in range(retries):
        try:
            with closing(sqlite3.connect(_get_db_path(), timeout=5)) as con:
                con.execute("PRAGMA busy_timeout=5000")
                return con.execute(query, params).fetchall()
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            logger.error("SQLite read failed: %s (query=%s)", e, query[:80])
            return []
        except Exception as e:
            logger.error("SQLite read failed: %s (query=%s)", e, query[:80])
            return []
    return []


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


# ── API safety ────────────────────────────────────────────────────────────────

_token_counter: dict = {"input": 0, "output": 0, "max_daily": 500_000, "reset_date": ""}
_token_counter_lock = threading.Lock()
_circuit_breaker: dict = {"consecutive_failures": 0, "paused_until": 0.0}
_CIRCUIT_BREAKER_THRESHOLD = 3
_CIRCUIT_BREAKER_PAUSE = 300  # 5 minutes


def _reset_token_counter_if_new_day() -> None:
    """Reset daily token counts at date change. Caller must hold ``_token_counter_lock``."""
    today = date.today().isoformat()
    if _token_counter["reset_date"] != today:
        _token_counter["input"] = 0
        _token_counter["output"] = 0
        _token_counter["reset_date"] = today


def _maybe_reset_token_counter() -> None:
    """Reset the daily token counter at midnight (thread-safe)."""
    with _token_counter_lock:
        _reset_token_counter_if_new_day()


def _llm(
    client: anthropic.Anthropic,
    model: str,
    messages: list,
    system: str = "",
    max_tokens: int = 1024,
    web_search: bool = False,
) -> str:
    """Single LLM call or agentic web-search loop with budget cap and circuit breaker."""
    with _token_counter_lock:
        _reset_token_counter_if_new_day()
        total_tokens = _token_counter["input"] + _token_counter["output"]
        if total_tokens > _token_counter["max_daily"]:
            logger.critical(
                "Daily token budget exceeded (%d tokens) — skipping LLM call", total_tokens
            )
            return ""

    # Circuit breaker check
    now = time.time()
    if _circuit_breaker["consecutive_failures"] >= _CIRCUIT_BREAKER_THRESHOLD:
        if now < _circuit_breaker["paused_until"]:
            logger.warning(
                "Circuit breaker OPEN — skipping LLM call (resumes in %.0fs)",
                _circuit_breaker["paused_until"] - now,
            )
            return ""
        _circuit_breaker["consecutive_failures"] = 0
        logger.info("Circuit breaker CLOSED — resuming LLM calls")

    tools = [{"type": "web_search_20250305", "name": "web_search"}] if web_search else []
    msgs = list(messages)
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": msgs}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    resp = None
    try:
        for _ in range(8):
            resp = client.messages.create(**kwargs)
            # Track token usage
            if hasattr(resp, "usage"):
                with _token_counter_lock:
                    _reset_token_counter_if_new_day()
                    _token_counter["input"] += resp.usage.input_tokens
                    _token_counter["output"] += resp.usage.output_tokens
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
        # Success — reset circuit breaker
        _circuit_breaker["consecutive_failures"] = 0
    except Exception as e:
        _circuit_breaker["consecutive_failures"] += 1
        if _circuit_breaker["consecutive_failures"] >= _CIRCUIT_BREAKER_THRESHOLD:
            _circuit_breaker["paused_until"] = time.time() + _CIRCUIT_BREAKER_PAUSE
            logger.error(
                "Circuit breaker OPEN after %d failures — pausing for %ds: %s",
                _CIRCUIT_BREAKER_THRESHOLD,
                _CIRCUIT_BREAKER_PAUSE,
                e,
            )
        else:
            logger.error(
                "LLM call failed (%d/%d): %s",
                _circuit_breaker["consecutive_failures"],
                _CIRCUIT_BREAKER_THRESHOLD,
                e,
            )
        return ""

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


def sim_analyze(state: AgentState) -> dict:
    """Rule-based analyzer — no LLM, uses simulated RSI."""
    logs = [_entry(f"[SIM] analyze: round={state['round']}")]

    prices = state["prices"]
    pv = _portfolio_value(state)

    # Compute RSI per symbol and pick best candidate
    rsi_map: dict[str, float] = {
        sym: _rsi(_sim_price_history.get(sym, [prices[sym]])) for sym in WATCHLIST if sym in prices
    }
    logs.append(_entry(f"[SIM] RSI: {rsi_map}"))

    # Choose action
    oversold = {s: r for s, r in rsi_map.items() if r < 30}
    overbought = {s: r for s, r in rsi_map.items() if r > 70 and s in state["positions"]}

    if overbought:
        sym = min(overbought, key=overbought.get)  # most overbought held pos
        action = "SELL"
        conf = 0.75
        alloc = 0
        sell_p = 100
        rsi_v = rsi_map[sym]
    elif oversold and len(state["positions"]) < MAX_POSITIONS:
        sym = min(oversold, key=oversold.get)  # most oversold on watchlist
        action = "BUY"
        conf = 0.80
        alloc = random.randint(15, MAX_ALLOC_PCT)
        sell_p = 0
        rsi_v = rsi_map[sym]
    else:
        sym = random.choice(WATCHLIST) if WATCHLIST else ""
        action = "HOLD"
        conf = 0.55
        alloc = 0
        sell_p = 0
        rsi_v = rsi_map.get(sym, 50.0)

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
    reasoning = f"RSI={rsi_v:.1f} → {action}. " f"Portfolio ${pv:.2f} | {emotion}"

    decision = {
        "thoughts": thoughts,
        "emotion": emotion,
        "action": action,
        "symbol": sym,
        "allocation_pct": alloc,
        "sell_pct": sell_p,
        "reasoning": reasoning,
        "confidence": conf,
        "market_intel": f"Simulated RSI={rsi_v:.1f}",
    }

    skip = state["skip_research"] or (not state["positions"] and conf >= 0.60)
    logs.append(_entry(f"[SIM] {action} {sym} conf={conf:.0%} emotion={emotion} RSI={rsi_v:.1f}"))

    return {
        "decision": decision,
        "confidence": conf,
        "emotion": emotion,
        "thoughts": thoughts,
        "skip_research": skip,
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


# ── .env writer (for Dash mode toggle) ───────────────────────────────────────


def _write_env_var(key: str, value: str) -> None:
    env_path = Path(__file__).parent.parent.parent / ".env"
    try:
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}")
        env_path.write_text("\n".join(lines) + "\n")
    except Exception as e:
        logger.warning("Failed to write %s to .env: %s", key, e)


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

    rows = _db_read(
        "SELECT timestamp,symbol,action,price,amount_usd,shares,"
        "reasoning,confidence,emotion,portfolio_value_after,lesson "
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
    )
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


def analyze_node(state: AgentState) -> dict:
    if _sim_mode["enabled"]:
        return sim_analyze(state)

    it = state["research_iterations"]
    logs = [_entry(f"analyze: round={state['round']} research_iter={it}")]

    pv = _portfolio_value(state)
    mode = (
        "PANIC"
        if pv < INITIAL_BALANCE * 0.5
        else "GREED" if pv > INITIAL_BALANCE * 1.5 else "NORMAL"
    )

    positions_display = {
        sym: {
            "shares": round(pos["shares"], 4),
            "avg_price": round(pos.get("avg_price", pos.get("avg_cost", 0)), 2),
            "now": round(state["prices"].get(sym, 0), 2),
            "pnl%": round(
                (
                    (
                        state["prices"].get(sym, 1)
                        / max(pos.get("avg_price", pos.get("avg_cost", 1)), 0.01)
                    )
                    - 1
                )
                * 100,
                2,
            ),
        }
        for sym, pos in state["positions"].items()
    }
    patterns_txt = (
        "\n".join(f"  • {p}" for p in state["known_patterns"]) or "  Aucun pattern enregistré"
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

    text = _llm(
        sonnet,
        SONNET_ID,
        [{"role": "user", "content": user}],
        system=system,
        max_tokens=1024,
        web_search=True,
    )

    decision = validate_decision(_parse_json_obj(text))
    confidence = decision["confidence"]
    emotion = decision["emotion"]
    thoughts = decision["thoughts"]

    # skip_research: no positions + conf ok, or flat market (already set in fetch_data)
    skip = state["skip_research"] or (not state["positions"] and confidence >= 0.60)

    logs.append(
        _entry(
            f"analyze: {decision.get('action')} {decision.get('symbol') or ''} "
            f"conf={confidence:.0%} emotion={emotion} skip_research={skip}"
        )
    )
    if thoughts:
        logs.append(_entry(f"thoughts: {thoughts[:140]}"))

    return {
        "decision": decision,
        "confidence": confidence,
        "emotion": emotion,
        "thoughts": thoughts,
        "skip_research": skip,
        "log": logs,
    }


def research_node(state: AgentState) -> dict:
    if _sim_mode["enabled"]:
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
        pv = portfolio.total_value(prices)
        logs = [_entry(f"execute: {action} {symbol}")]

        result: dict = {"success": False, "error": "no-op"}

        # Stop-loss check on all open positions before executing the agent decision
        for sl_sym, sl_pos in list(portfolio.positions.items()):
            sl_price = prices.get(sl_sym, 0.0)
            sl_avg = sl_pos.get("avg_price", sl_pos.get("avg_cost", 0))
            if sl_avg <= 0:
                continue
            if sl_price <= 0:
                logs.append(
                    _entry(
                        f"Skipping stop-loss check for {sl_sym}: invalid price "
                        f"sl_price={sl_price}, sl_avg={sl_avg}",
                        "warning",
                    )
                )
                continue
            # Sub-dollar legitimate positions: allow SL when basis and quote are both cheap.
            penny_pair = sl_avg <= 1.0 and sl_price <= 1.0
            plausible_quote = sl_price > 1.0 or penny_pair
            if not plausible_quote:
                logs.append(
                    _entry(
                        f"Skipping stop-loss check for {sl_sym}: invalid price "
                        f"sl_price={sl_price}, sl_avg={sl_avg}",
                        "warning",
                    )
                )
                continue
            sl_pct = (sl_price - sl_avg) / sl_avg
            if sl_pct < -STOP_LOSS_PCT:
                sl_slip = 1 + random.uniform(-0.001, 0.001)
                portfolio.sell(sl_sym, 100, sl_price * sl_slip)
                logs.append(
                    _entry(
                        f"STOP-LOSS triggered: {sl_sym} @ ${sl_price:.2f} (loss: {sl_pct:.1%})",
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
                portfolio.save_state(DB_PATH.parent / ".apex7_state.json")

        elif action == "SELL" and symbol:
            slip = 1 + random.uniform(-0.001, 0.001)
            price = prices.get(symbol, 0) * slip
            result = portfolio.sell(symbol, sell_pct, price)
            if result["success"]:
                logs.append(
                    _entry(
                        f"SELL {symbol} {sell_pct:.0f}% @ ${price:.2f} "
                        f"= ${result['amount']:.2f}  slip={slip-1:+.3%}"
                    )
                )
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
            "balance": portfolio.cash,
            "positions": dict(portfolio.positions),
            "portfolio_history": [new_pv],
            "alive": not portfolio.is_dead,
            "log": logs,
        }

    return execute_node


def make_save_memory_node(portfolio: Portfolio):
    def save_memory_node(state: AgentState) -> dict:
        decision = state.get("decision") or {}
        action = decision.get("action", "HOLD").upper()
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
            lesson = _llm(
                haiku, HAIKU_ID, [{"role": "user", "content": lesson_prompt}], max_tokens=80
            ).strip()

        success = _db_write_multi(
            [
                (
                    "INSERT INTO trades "
                    "(timestamp,symbol,action,price,amount_usd,shares,"
                    "reasoning,confidence,emotion,portfolio_value_after,lesson,source) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        _ts(),
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
                        source,
                    ),
                ),
                (
                    "INSERT INTO patterns (timestamp, pattern) VALUES (?,?)",
                    (_ts(), lesson),
                ),
            ]
        )
        if not success:
            logs.append(_entry("save_memory: DB write failed", "error"))

        logs.append(_entry(f"save_memory: lesson → {lesson[:90]}"))
        return {
            "known_patterns": state["known_patterns"] + [lesson],
            "log": logs,
        }

    return save_memory_node


def skip_node(state: AgentState) -> dict:
    decision = state.get("decision") or {}
    reason = decision.get("_risk_reason") or "trade rejected by risk_check"
    return {"log": [_entry(f"skip: {reason}", "warning")]}


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════════════════════


def _route_analyze(state: AgentState) -> str:
    if (
        state.get("skip_research")
        or state["confidence"] >= 0.70
        or state["research_iterations"] >= 2
    ):
        return "risk_check"
    return "research"


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
