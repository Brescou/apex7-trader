# Architecture

## Simple Graph

```
__start__
    │
load_memory   (Haiku — SQLite query + pattern extraction)
    │
fetch_data    (no LLM — async parallel: prices + news + sentiment)
    │
analyze       (Sonnet + web_search — JSON decision)
    │
  conf ≥ 0.70 or iters ≥ 2 or skip_research
    │                   │
 risk_check          research   (Sonnet + web_search, max 2×)
    │                   │
  _risk_passed         analyze  (loop back)
    │        │
 execute    skip
    │
save_memory  (Haiku — lesson generation + SQLite INSERT)
    │
__end__
```

## Multi-Agent Graph

```
__start__
    │
load_memory   (Haiku)
    │
fetch_data    (no LLM)
    │
supervisor    (Haiku — 3-point context brief)
    │
   Send × 4 (parallel fan-out)
    ├── technician    (Haiku — RSI + indicators)
    ├── analyst       (Sonnet + web_search — fundamentals + sentiment)
    ├── risk_manager  (Haiku — VaR, Kelly, risk score)
    └── macro_watcher (Haiku — regime, bias, sector rotation)
    │
arbitrate     (Sonnet — weighted vote synthesis)
    │
  conf ≥ 0.72 or iters ≥ 2 or skip_research
    │                   │
 risk_check          research   (Sonnet + web_search)
    │                   │
  _risk_passed        risk_check
    │        │
 execute    skip
    │
save_memory  (Haiku)
    │
__end__
```

Note: in the multi-agent graph, `research` edges directly to `risk_check` (no loop back to `arbitrate`).

## Specialized Agents

| Agent | Model | Role | Notes |
|-------|-------|------|-------|
| `supervisor` | Haiku | Context brief for the team | 60-word summary, 3 key points |
| `technician` | Haiku | Technical analysis — RSI, MACD, Bollinger Bands, trend | Directional vote |
| `analyst` | Sonnet + web_search | Fundamental + sentiment analysis, catalysts | Directional vote |
| `risk_manager` | Haiku | VaR, Kelly sizing, risk score /10 | No directional vote — HOLD only |
| `macro_watcher` | Haiku | Market regime, macro bias, sector rotation | No directional vote — HOLD only |
| `arbitrate` | Sonnet | Weighted vote synthesis, final decision | Applies risk veto + macro filter |

## Vote Weights

Static base weights:

| Agent | Weight | Votes on direction |
|-------|--------|--------------------|
| technician | 0.30 | yes |
| analyst | 0.35 | yes |
| risk_manager | 0.20 | no (sizing only) |
| macro_watcher | 0.15 | no (regime only) |

Risk veto: `risk_score > 8` → BUY penalized ×0.15.
Macro filter: `regime == "risk-off"` → BUY dampened ×0.5.

**Dynamic weights** (`_compute_dynamic_weights` in `agent_multi.py`):
- Blends static weights (70%) with accuracy-based weights (30%) derived from the last 50 scored `agent_memory` votes per agent
- Result is cached for 10 minutes; recomputed lazily on the next `arbitrate_node` call after expiry
- Falls back to static weights if `agent_memory` has insufficient data

## StateGraph — Nodes & Edges

### Simple graph (`agent.py`)

| Node | Incoming | Outgoing |
|------|----------|----------|
| `load_memory` | START | `fetch_data` |
| `fetch_data` | `load_memory` | `analyze` |
| `analyze` | `fetch_data`, `research` | `risk_check` / `research` (conditional) |
| `research` | `analyze` | `analyze` |
| `risk_check` | `analyze` | `execute` / `skip` (conditional) |
| `execute` | `risk_check` | `save_memory` |
| `save_memory` | `execute` | END |
| `skip` | `risk_check` | END |

### Multi-agent graph (`agent_multi.py`)

| Node | Incoming | Outgoing |
|------|----------|----------|
| `load_memory` | START | `fetch_data` |
| `fetch_data` | `load_memory` | `supervisor` |
| `supervisor` | `fetch_data` | `technician`, `analyst`, `risk_manager`, `macro_watcher` (Send fan-out) |
| `technician` | `supervisor` (Send) | `arbitrate` |
| `analyst` | `supervisor` (Send) | `arbitrate` |
| `risk_manager` | `supervisor` (Send) | `arbitrate` |
| `macro_watcher` | `supervisor` (Send) | `arbitrate` |
| `arbitrate` | all 4 specialists | `risk_check` / `research` (conditional) |
| `research` | `arbitrate` | `risk_check` |
| `risk_check` | `arbitrate`, `research` | `execute` / `skip` (conditional) |
| `execute` | `risk_check` | `save_memory` |
| `save_memory` | `execute` | END |
| `skip` | `risk_check` | END |

Shared nodes (imported from `agent.py` into `agent_multi.py`): `load_memory`, `fetch_data`, `risk_check`, `execute`, `save_memory`, `skip`, `research`.

## SQLite Schema

```sql
CREATE TABLE trades (
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

CREATE TABLE patterns (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    pattern   TEXT
);

CREATE TABLE agent_memory (
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

CREATE TABLE postmortem (
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
```

`source` values: `'live'` or `'simulation'`.
`HOLD` actions are not persisted to `trades` (save_memory_node skips HOLDs).
`agent_memory.was_correct` is set by `arbitrate_node` after the final decision is known (NULL until then).
`postmortem` rows are written once per SELL trade by `run_daily_postmortem()` at `POSTMORTEM_HOUR`.

## Daily Postmortem

`run_daily_postmortem(portfolio, db_path)` in `agent_multi.py`:
- Triggered by a dedicated background thread (`apex7-postmortem`, daemon) started in `app.py`
- Runs at `POSTMORTEM_HOUR` (default 22:00) once per calendar day
- Scans `portfolio.trade_history` for SELL trades since midnight
- For each SELL, finds the matching BUY, computes P&L % and holding duration in hours
- Queries `agent_memory` for agents that voted SELL correctly on that symbol
- Generates a 2-sentence summary via Haiku (simulation: rule-based string)
- Inserts one row into `postmortem` per trade

## Dash Dashboard

| Tab | Content | Refresh |
|-----|---------|---------|
| LIVE | Portfolio value, agent state, equity curve, activity log, agent cards (multi mode), Track Records badges | 2s interval |
| ANALYTICS | KPI row, 4 charts, full trade table | 30s + manual |
| BACKTEST | Scenario/config selector, portfolio vs SPY chart, trade log | on button click |
| LEADERBOARD | Scenario selector, ranked agent comparison table | on button click |
| HEATMAP | Per-symbol return heatmap + trade frequency matrix | on button click |
| AGENTS | Per-agent accuracy, confidence, win-rate comparison table | on button click |
| TERMINAL | Macro header bar (VIX/SPY/DXY), watchlist table, screener, news feed | macro: 60s, watchlist: 10s, news: 120s |

New `dcc.Store` ids (TERMINAL tab):

| Store id | Purpose |
|----------|---------|
| `terminal-watchlist` | List of symbols shown in the watchlist (initialized from config.WATCHLIST) |
| `terminal-active-symbol` | Currently selected symbol for the news feed |

New `dcc.Interval` ids (TERMINAL tab):

| Interval id | Period | Drives |
|-------------|--------|--------|
| `macro-interval` | 60s | Macro header bar refresh |
| `watchlist-interval` | 10s | Watchlist table refresh |
| `news-interval` | 120s | News feed refresh |

Agent cards panel (LIVE tab, multi-agent mode only):
- TECH (blue), ANLST (green), RISK (orange), MACRO (purple) — each collapsible
- ARBITRATION card always visible below agent cards

Agent Track Records badges (LIVE tab, multi-agent mode only):
- One badge per agent showing accuracy rate (correct votes / total votes from `agent_memory`)
- Only visible when `AGENT_GRAPH=multi`

Controls (top bar): PAUSE / STEP / RESET buttons, SIM/LIVE radio, graph selector dropdown.

## Data Classes

### `Portfolio` (`data.py`)

Thread-safe portfolio state. All mutations protected by `threading.RLock()`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `cash` | float | Available cash |
| `positions` | dict | `{symbol: {shares, avg_price}}` — max 1 position per symbol |
| `trade_history` | list | All executed trades (in-memory) |
| `value_history` | list | `[{time, value}]` snapshots |
| `agent_log` | list | `[{time, message, level}]` |
| `is_dead` | bool | True when total value < DEATH_THRESHOLD |
| `last_prices` | dict | Last fetched prices cache |
| `peak_value` | float | All-time peak portfolio value (updated in `record_value`) |

Key methods:

| Method | Description |
|--------|-------------|
| `buy(symbol, amount_usd, price)` | Opens position; returns `{"success": False, "error": "position already open"}` if symbol already held |
| `sell(symbol, sell_pct, price)` | Closes or reduces position |
| `open_symbols()` | Returns list of currently held symbols |
| `closed_trades_since(ts)` | Returns SELL trades from `trade_history` with `time >= ts` |
| `fetch_prices(symbols)` | Fetches live prices via `yf.Tickers` fast_info |
| `total_value(prices)` | Cash + sum of position values |
| `record_value(prices)` | Appends snapshot to `value_history`; updates `peak_value` |
| `check_death(prices)` | Sets `is_dead = True` if total value < DEATH_THRESHOLD |
| `save_state(path)` | Serializes cash/positions/history/peak_value to JSON |
| `load_state(path)` | Restores state from JSON (no-op if file absent) |

### `BacktestEngine` (`backtest.py`)

Self-contained simulation engine — no LLM calls, no network, no shared state with `agent.py`.

```python
engine = BacktestEngine(scenario="Bull Market", config={"max_alloc_pct": 25})
result = engine.run(n_cycles=100)
# result keys: return_pct, sharpe, max_drawdown, win_rate, survived,
#              portfolio_history, trades_count, trade_log
```

4 built-in scenarios:

| Scenario | Drift | Volatility |
|----------|-------|------------|
| Bull Market | +0.0005 | 0.020 |
| Bear Market | −0.0003 | 0.025 |
| High Volatility | 0.0 | 0.050 |
| Flat Market | 0.0 | 0.005 |

Price model: GBM step `price *= (1 + drift + vol * N(0,1))`.
Decision rule: RSI < 35 → BUY, RSI > 65 → SELL.

### `Leaderboard` (`leaderboard.py`)

Runs `BacktestEngine` for 4 allocation strategies over 80 cycles and ranks by return_pct:

| Agent ID | max_alloc_pct |
|----------|--------------|
| CONSERVATIVE | 15% |
| BALANCED | 25% |
| AGGRESSIVE | 40% |
| APEX-7 | `MAX_ALLOC_PCT` (config) |

### `LiveFeed` (`data.py`)

Fetches 1-minute interval prices for one or more symbols via yfinance.

```python
feed = LiveFeed(["AAPL", "MSFT"])
prices = feed.fetch()  # -> {"AAPL": 185.0, "MSFT": 415.0}
```

Currently defined but not wired into the agent graph.

## Concurrency Model

- Dash callback thread: reads `_state["portfolio"]` — no mutations
- Agent loop thread (`apex7-agent`, daemon): mutates Portfolio via `buy()`, `sell()`, `record_value()`
- Postmortem thread (`apex7-postmortem`, daemon): calls `run_daily_postmortem()` once per day — reads `portfolio.trade_history`, writes to SQLite
- All Portfolio mutations use `with self._lock` (RLock)
- `_ctrl` dict (pause/step) and `_state` dict are mutated by both threads — not lock-protected (acceptable: only booleans and references)
- Graph switch and reset: agent thread is killed (portfolio.is_dead = True), new Portfolio + thread created

## market_data.py — Standalone Market Data Module

Zero imports from `agent.py` or `agent_multi.py`. Used exclusively by `app.py` TERMINAL tab callbacks.

| Function | Cache TTL | Description |
|----------|-----------|-------------|
| `fetch_macro()` | 60s | Fetches VIX (`^VIX`), SPY, DXY (`DX-Y.NYB`) via yfinance; returns price, change_pct, direction; fallback to last known value on error |
| `fetch_watchlist_prices(symbols)` | 10s | Per-symbol: price, change_pct, change_abs, volume, high_52w, low_52w, rsi_14 (14-day daily close), above_ma20 (bool) |
| `fetch_news(symbol, max_items)` | none | Uses `yf.Ticker.news`; returns title, source, age ("Xm/Xh/Xd ago"), url, sentiment (positive/negative/neutral via keyword rule) |
| `run_screener(symbols, filters)` | n/a | Reuses `fetch_watchlist_prices()`; filters: rsi_min/max, change_pct_min, above_ma20, volume_min; returns list of passing symbols |

Cache uses `threading.Lock()` — thread-safe for concurrent Dash callbacks.

## Configuration

| Constant | Source | Default | Effect |
|----------|--------|---------|--------|
| `ANTHROPIC_API_KEY` | env | — | Required for live mode |
| `SIMULATION_MODE` | env | `false` | Skip all network/LLM calls |
| `SIM_VOLATILITY` | env | `0.02` | Price random-walk std dev per step |
| `SIM_DRIFT` | env | `0.0001` | Price drift per step |
| `AGENT_GRAPH` | env | `simple` | `simple` or `multi` |
| `X_BEARER_TOKEN` | env | — | Twitter/X sentiment (optional) |
| `MACRO_SYMBOLS` | hardcoded | `{"VIX": "^VIX", "SPY": "SPY", "DXY": "DX-Y.NYB"}` | Symbols fetched for TERMINAL macro bar |
| `MARKET_DATA_CACHE_SEC` | hardcoded | `60` | Macro cache TTL in `market_data.py` |
| `WATCHLIST_CACHE_SEC` | hardcoded | `10` | Watchlist prices cache TTL in `market_data.py` |
| `NEWS_MAX_ITEMS` | hardcoded | `8` | Max news items from `fetch_news()` |
| `STOP_LOSS_PCT` | hardcoded | `0.05` | Stop-loss threshold (5%) — enforced as a pre-check loop in `execute_node` before the agent decision |
| `POSTMORTEM_HOUR` | hardcoded | `22` | Hour (0–23) at which daily postmortem runs |
| `WATCHLIST` | hardcoded | 5 tickers | AAPL, MSFT, GOOG, AMZN, TSLA |
| `INITIAL_BALANCE` | hardcoded | `1000` | Starting cash |
| `DEATH_THRESHOLD` | hardcoded | `50.0` | Portfolio floor |
| `MAX_POSITIONS` | hardcoded | `3` | Max simultaneous positions |
| `MAX_ALLOC_PCT` | hardcoded | `40` | Max % portfolio per trade |
| `AGENT_INTERVAL` | hardcoded | `30` | Seconds between live cycles (3s in sim) |
