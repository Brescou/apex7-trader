# Architecture

## Repo Structure

```
apex7-trader/
├── main.py
├── config.py
├── market_data.py
├── leaderboard.py
├── pyproject.toml
├── langgraph.json
├── README.md → docs/README.md
├── agents/
│   ├── __init__.py
│   ├── simple.py          ← simple graph (was agent.py)
│   ├── multi.py           ← multi-agent graph (was agent_multi.py)
│   └── shared/
│       ├── __init__.py
│       ├── state.py       ← AgentState, MultiAgentState TypedDicts
│       ├── nodes.py       ← shared nodes, _db_write, _llm, sim engine
│       ├── prompts.py     ← versioned system prompts (PROMPT_VERSION)
│       └── schemas.py     ← Pydantic validation for LLM outputs
├── core/
│   ├── __init__.py
│   ├── data.py            ← Portfolio, LiveFeed
│   ├── backtest.py        ← BacktestEngine, run_backtest
│   ├── indicators.py      ← Shared RSI implementation
│   └── registry.py        ← graph ID → builder map
├── dashboard/
│   ├── __init__.py        ← create_app()
│   ├── server.py          ← Dash() init + design tokens + /health endpoint
│   ├── controller.py      ← agent loop, portfolio state, postmortem thread
│   ├── layout/            ← app.layout + UI helpers (split into sub-modules)
│   │   ├── __init__.py
│   │   ├── helpers.py
│   │   ├── emotions.py
│   │   ├── classify.py
│   │   ├── live_tab.py
│   │   ├── terminal_tab.py
│   │   ├── analytics_tab.py
│   │   └── main.py
│   └── callbacks/
│       ├── __init__.py    ← imports all callback modules
│       ├── live.py
│       ├── analytics.py
│       ├── backtest_tab.py
│       ├── leaderboard_tab.py
│       ├── heatmap.py
│       ├── agents.py
│       └── terminal.py
├── docs/
│   ├── ARCHITECTURE.md  (this file)
│   ├── CHANGELOG.md
│   └── README.md
├── tests/
│   ├── conftest.py
│   ├── test_circuit_breaker.py
│   ├── test_integration.py
│   ├── test_layout_helpers.py
│   ├── test_smoke.py
│   ├── test_stoploss.py
│   └── test_terminal.py
├── .github/
│   └── workflows/
│       └── ci.yml
└── .pre-commit-config.yaml
```

## Package Dependency Graph

```
main.py
  └── dashboard (create_app → start_controller → layout → callbacks)
        ├── dashboard.server (Dash app, design tokens, /health endpoint)
        ├── dashboard.controller (agent loop thread, portfolio init)
        ├── dashboard.layout (UI helpers, app.layout — split into sub-modules)
        └── dashboard.callbacks.* (all @app.callback)
              ├── core.data (Portfolio)
              ├── core.backtest (run_backtest)
              ├── core.registry (build_graph)
              └── market_data (fetch_*)

core.registry
  ├── agents.simple (build_simple_graph)
  └── agents.multi (build_multi_graph)
        └── agents.shared.nodes, agents.shared.state
              └── core.data (Portfolio)
```

Import direction is one-way: `dashboard` → `core`/`agents`/`market_data`. Never import from `dashboard` inside `agents/` or `core/`.

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

**Dynamic weights** (`_compute_dynamic_weights` in `agents/multi.py`):
- Blends static weights (70%) with accuracy-based weights (30%) derived from the last 50 scored `agent_memory` votes per agent
- Result is cached for 10 minutes; recomputed lazily on the next `arbitrate_node` call after expiry
- Falls back to static weights if `agent_memory` has insufficient data

## StateGraph — Nodes & Edges

### Simple graph (`agents/simple.py`)

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

### Multi-agent graph (`agents/multi.py`)

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

Shared nodes (defined in `agents/shared/nodes.py`, imported by both `agents/simple.py` and `agents/multi.py`): `load_memory`, `fetch_data`, `risk_check`, `execute`, `save_memory`, `skip`, `research`.

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
    trace_id              TEXT,
    prompt_version        TEXT,
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

`run_daily_postmortem(portfolio, db_path)` in `agents/multi.py`:
- Triggered by a dedicated background thread (`apex7-postmortem`, daemon) started in `dashboard/controller.py`
- Runs at `POSTMORTEM_HOUR` (default 22:00) once per calendar day
- Scans `portfolio.trade_history` for SELL trades since midnight
- For each SELL, finds the matching BUY, computes P&L % and holding duration in hours
- Queries `agent_memory` for agents that voted SELL correctly on that symbol
- Generates a 2-sentence summary via Haiku (simulation: rule-based string)
- Inserts one row into `postmortem` per trade

## Dash Dashboard

### Tab architecture

All 7 tab content divs are always present in the DOM (`id` = `tab-live`, `tab-analytics`, `tab-backtest`, `tab-leaderboard`, `tab-heatmap`, `tab-agents`, `tab-terminal`). Visibility is toggled via CSS `display` by the `_show_tab` callback in `dashboard/callbacks/live.py` — no HTML reconstruction on tab switch.

| Tab | Content | Refresh |
|-----|---------|---------|
| LIVE | Portfolio value, agent state, equity curve, activity log, agent cards (multi mode), Track Records badges | 2s interval |
| ANALYTICS | KPI row, 4 charts, full trade table | 30s + manual; `no_update` guard when tab not active |
| BACKTEST | Symbol input, period dropdown, strategy selector (simple/multi), RUN BACKTEST button; KPI row (return, vs benchmark, win rate, max drawdown, Sharpe); equity curve with SPY benchmark overlay and BUY/SELL trade markers; trade log table with P&L per row | on button click |
| LEADERBOARD | Scenario selector, ranked agent comparison table | on button click |
| HEATMAP | Per-symbol return heatmap + trade frequency matrix | on button click |
| AGENTS | Per-agent accuracy, confidence, win-rate comparison table; `no_update` guard when tab not active | on button click |
| TERMINAL | 65/35 split: left = 64px macro bar + 2-col symbol cards; right = chart overlay panel + news feed panel + compact screener | macro: 60s, watchlist: 10s, news: 120s |

### Terminal tab components

| Component / div id | Description |
|--------------------|-------------|
| `macro-bar-content` | VIX / SPY / DXY blocs — price, change_pct, 80×30px mini sparkline per symbol |
| `watchlist-table` | 2-column symbol card grid — price, change_pct, RSI badge, MA20 indicator, volume, sparkline |
| `chart-overlay-content` | 1mo OHLCV area chart for the selected symbol; max/min annotations; driven by `fetch_ohlcv()` |
| `news-feed-content` | News cards for the selected symbol; sentiment-coloured left border; tab-gated |
| `screener-results` | Screener matches list |
| `screener-results-store` | List of matched symbol strings (for watchlist card highlighting) |
| `screener-active-store` | Bool — true when screener has been run and not cleared |

### Terminal tab callbacks (`dashboard/callbacks/terminal.py`)

| Callback | Trigger | Output |
|----------|---------|--------|
| `_update_macro_bar` | `macro-interval` | `macro-bar-content` — blocs with mini sparklines |
| `_update_watchlist` | `watchlist-interval`, `terminal-watchlist`, `terminal-active-symbol`, screener stores | `watchlist-table` (2-col card grid) |
| `_update_news_content` | `terminal-active-symbol`, `news-interval` | `news-feed-content`; tab-gated |
| `_update_chart_overlay` | `terminal-active-symbol` | `chart-overlay-content`; tab-gated |
| `_run_screener` | `btn-screener-run` | 3-tuple: `screener-results`, `screener-results-store`, `screener-active-store` |
| `_clear_screener` | `btn-screener-clear` | resets `screener-active-store` + `screener-results-store` |

### dcc.Store ids

| Store id | Purpose |
|----------|---------|
| `terminal-watchlist` | List of symbols shown in the watchlist (initialized from config.WATCHLIST) |
| `terminal-active-symbol` | Currently selected symbol for chart overlay and news feed |
| `screener-results-store` | List of symbols matched by the most recent screener run |
| `screener-active-store` | Bool — whether screener results are currently active (for watchlist card highlighting) |

### dcc.Interval ids

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

### `BacktestEngine` and functional API (`backtest.py`)

Self-contained engine — no LLM calls, deterministic rules only. Two interfaces:

**Functional API (Sprint 4, primary):**

```python
from backtest import fetch_historical, compute_indicators, run_backtest, compare_strategies

df = fetch_historical("AAPL", period="6mo", interval="1d")  # yfinance OHLCV DataFrame
df = compute_indicators(df)   # adds RSI_14, MA_20, MA_50, MACD, BB_upper, BB_lower
result = run_backtest("AAPL", strategy="simple", period="6mo", initial_cash=1000.0, stop_loss_pct=0.05)
# result keys: symbol, period, strategy, trades, final_value, total_return_pct,
#              win_rate, max_drawdown_pct, sharpe_ratio, n_trades,
#              benchmark_return_pct, vs_benchmark, equity_curve
both = compare_strategies("AAPL", period="6mo")  # runs both "simple" and "multi"
```

Strategies: `"simple"` (RSI<30 → BUY, RSI>70 → SELL), `"multi"` (same + simulated majority vote TECH+ANLST).

**Class-based API (legacy, still present):**

```python
engine = BacktestEngine(scenario="Bull Market", config={"max_alloc_pct": 25})
result = engine.run(n_cycles=100)
# result keys: return_pct, sharpe, max_drawdown, win_rate, survived,
#              portfolio_history, trades_count, trade_log
```

4 built-in GBM scenarios: Bull Market (+0.0005 drift / 0.020 vol), Bear Market (−0.0003 / 0.025), High Volatility (0.0 / 0.050), Flat Market (0.0 / 0.005).

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

Wired into `Portfolio.fetch_prices()` when `USE_LIVEFEED=True`. If `LiveFeed.fetch()` raises or returns empty, `Portfolio.fetch_prices()` falls back to `yf.Tickers` fast_info silently. The `LiveFeed` instance is created lazily once per `Portfolio` instance.

## Concurrency Model

- Dash callback thread: reads `_state["portfolio"]` — no mutations
- Agent loop thread (`apex7-agent`, daemon): mutates Portfolio via `buy()`, `sell()`, `record_value()` — launched by `start_controller()` in `dashboard/controller.py`
- Postmortem thread (`apex7-postmortem`, daemon): calls `run_daily_postmortem()` once per day — reads `portfolio.trade_history`, writes to SQLite
- All Portfolio mutations use `with self._lock` (RLock)
- SQLite writes go through `_db_write()` in `agents/shared/nodes.py` — handles WAL mode, retries (3 attempts with backoff), and structured logging
- Sim and live use separate databases (`trades_sim.db` / `trades.db`) via `_get_db_path()`
- `_ctrl` and `_state` in `dashboard/controller.py` share one **`threading.RLock()`** (`_controller_lock`) — all mutations and reads use `with _controller_lock`.
- Graph switch and reset: agent thread is stopped (`portfolio.is_dead = True`), new Portfolio + thread created

## market_data.py — Standalone Market Data Module

Zero imports from `agents/` or `dashboard/`. Used exclusively by `dashboard/callbacks/terminal.py` callbacks.

| Function | Cache TTL | Description |
|----------|-----------|-------------|
| `fetch_macro()` | 60s | Fetches VIX (`^VIX`), SPY, DXY (`DX-Y.NYB`) via yfinance; returns price, change_pct, direction; fallback to last known value on error |
| `fetch_watchlist_prices(symbols)` | 10s | Per-symbol: price, change_pct, change_abs, volume, high_52w, low_52w, rsi_14 (14-day daily close), above_ma20 (bool) |
| `fetch_news(symbol, max_items)` | none | Uses `yf.Ticker.news`; returns title, source, age ("Xm/Xh/Xd ago"), url, sentiment (positive/negative/neutral via keyword rule) |
| `run_screener(symbols, filters)` | n/a | Reuses `fetch_watchlist_prices()`; filters: rsi_min/max, change_pct_min, above_ma20, volume_min; returns list of passing symbols |
| `fetch_sparkline(symbol)` | 5 min | 1-day hourly OHLC via yfinance; returns `[{"time": "14:00", "price": 182.5, "open": 181.0}, ...]`; empty list on failure |
| `fetch_comparison(symbols, period)` | 5 min | Daily closes normalized to 100.0 at first point; returns `{"AAPL": [{"date": "...", "value": 100.0}, ...], ...}`; empty dict on failure |
| `fetch_ohlcv(symbol, period)` | 5 min per `(symbol, period)` | Daily OHLCV; returns `[{"date": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]`; empty list on failure; never raises |

Cache uses `threading.Lock()` — thread-safe for concurrent Dash callbacks. Separate lock per cache (`_sparkline_lock`, `_comparison_lock`).

## CI/CD Pipeline

```
push / PR to master
        │
        ▼
  GitHub Actions (.github/workflows/ci.yml)
        │
        ├── job: test (ubuntu-latest)
        │     ├── uv python install 3.12
        │     ├── uv sync
        │     ├── ruff check . --select E,F,W --ignore E501
        │     └── pytest tests/ -v --tb=short   (SIMULATION_MODE=true)
        │
        └── job: lint (ubuntu-latest)
              ├── uv sync
              └── black --check --diff .
```

Pre-commit hooks (`.pre-commit-config.yaml`): ruff (auto-fix) + black + trailing-whitespace + end-of-file-fixer + check-yaml + check-json + check-merge-conflict.

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
