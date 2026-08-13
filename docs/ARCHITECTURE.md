# Architecture

## Repo Structure

```
apex7-trader/
├── main.py
├── config.py
├── market_data/           ← package : macro, cotations, news, earnings, charts, secteurs, corrélation, calendrier
│   ├── __init__.py
│   ├── caches.py
│   ├── compat.py
│   ├── helpers.py
│   ├── macro.py
│   ├── quotes.py
│   ├── news.py
│   ├── earnings.py
│   ├── charts.py
│   ├── sectors.py
│   ├── correlation.py
│   ├── economic_calendar.py
│   └── screener.py
├── pyproject.toml
├── langgraph.json
├── README.md → docs/README.md
├── agents/
│   ├── __init__.py
│   ├── multi.py           ← unique multi-agent graph (4 specialists + arbitration)
│   ├── registry.py        ← graph builder + UI metadata (imports agents.multi)
│   └── shared/
│       ├── __init__.py
│       ├── state.py       ← AgentState, MultiAgentState TypedDicts
│       ├── nodes.py       ← LangGraph nodes + sim engine (re-exports)
│       ├── db.py          ← SQLite, _db_write / _db_read
│       ├── modes.py       ← live / paper / sim
│       ├── llm.py         ← Anthropic clients, _llm, circuit breaker
│       ├── eval.py        ← evaluate_pending_trades
│       ├── watchlist.py   ← DB watchlist (max 20 symbols)
│       ├── prompts.py     ← versioned system prompts (PROMPT_VERSION)
│       └── schemas.py     ← Pydantic validation for LLM outputs
├── core/
│   ├── __init__.py
│   ├── data.py            ← Portfolio, LiveFeed
│   ├── notifications.py  ← Discord (trades, digest, weekly, evaluation)
│   ├── external_data.py  ← FRED + CNN Fear & Greed
│   ├── backtest.py        ← run_backtest, compare_strategies
│   └── indicators.py      ← Shared RSI implementation
├── dashboard/
│   ├── __init__.py
│   └── controller.py      ← agent loop, portfolio state, postmortem thread
├── api/                    ← FastAPI backend (HTTP/WS layer)
│   ├── main.py             ← FastAPI app + lifespan (starts controller + WS broadcaster)
│   ├── auth.py             ← Bearer-token REST auth + WS origin/token check
│   ├── broadcaster.py      ← ConnectionManager + poll_and_broadcast() (500ms)
│   ├── serializers.py      ← Portfolio + controller state → JSON snapshot
│   └── routes/
│       ├── ws.py           ← GET /ws (WebSocket)
│       ├── portfolio.py    ← GET /api/portfolio, /trades, /analytics
│       ├── market.py       ← GET /api/market/macro|watchlist|sectors|correlation|news|fundamentals|fear-greed
│       └── control.py      ← POST /api/control/mode|pause|resume + watchlist CRUD
├── frontend/                ← React 19 + Mantine 9 + Vite + TypeScript terminal UI
│   ├── src/
│   │   ├── App.tsx
│   │   ├── hooks/          ← useWebSocket.ts, useApex.ts (REST polling)
│   │   └── components/     ← live/, terminal/, analytics/, layout/
│   └── package.json
├── docs/
│   ├── ARCHITECTURE.md  (this file)
│   ├── CHANGELOG.md
│   └── README.md
├── tests/
│   ├── conftest.py
│   ├── test_circuit_breaker.py
│   ├── test_dynamic_weights.py
│   ├── test_evaluate_pending.py
│   ├── test_integration.py
│   ├── test_layout_helpers.py
│   ├── test_misc_coverage.py
│   ├── test_mode_toggle_ui.py
│   ├── test_notifications.py
│   ├── test_paper_mode.py
│   ├── test_paper_trading.py
│   ├── test_partial_exits.py
│   ├── test_pending_evaluations.py
│   ├── test_portfolio.py
│   ├── test_smoke.py
│   ├── test_stoploss.py
│   ├── test_terminal.py
│   ├── test_trailing_stop.py
│   └── test_was_correct.py
├── .github/
│   └── workflows/
│       └── ci.yml
└── .pre-commit-config.yaml
```

## Package Dependency Graph

```
main.py (uvicorn launcher)
  └── api.main (FastAPI app + lifespan)
        ├── api.auth (Bearer-token REST auth, WS origin/token check)
        ├── api.broadcaster (WebSocket hub, polls _state every 500ms)
        ├── api.serializers (Portfolio + controller state → JSON)
        ├── api.routes.* (portfolio, market, control, ws)
        └── dashboard.controller (start_controller — agent loop + postmortem threads)
              ├── core.data (Portfolio)
              ├── core.backtest (run_backtest)
              ├── agents.registry (get_graph)
              └── market_data (fetch_*)

frontend/ (React 19 + Mantine 9 + Vite + TypeScript)
  └── REST (/api/*) + WebSocket (/ws) → api.main

agents.registry
  └── agents.multi (build_multi_graph)
        └── agents.shared.nodes, agents.shared.state
              └── core.data (Portfolio)
              └── market_data, core.external_data (macro context, F&G, earnings)
```

Import direction is one-way: `api`/`dashboard` → `core`/`agents`/`market_data`. Never import from `api` or `dashboard` inside `agents/` or `core/`.

## Primary modules (`core/` & `agents/shared/`)

| Module | Role |
|--------|------|
| `core/external_data.py` | **FRED** (`fetch_fred_latest`, `fetch_macro_indicators`) and **CNN Fear & Greed** (`fetch_fear_greed`). Optional `FRED_API_KEY`. Standalone — must not import `agents/` or `dashboard/`. |
| `agents/shared/watchlist.py` | Dynamic **watchlist** backed by SQLite table `watchlist` (max **20** symbols, yfinance validation on add): `get_watchlist`, `add_to_watchlist`, `remove_from_watchlist`. |

## Agent Graph

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

Note: `research` edges directly to `risk_check` (no loop back to `arbitrate`). This is the only graph supported — no graph selector in the UI.

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
- Blends static weights (70%) with accuracy-based weights (30%) derived from the last 50 evaluated `agent_memory` votes per agent (`was_correct IS NOT NULL`).
- Result is cached for 10 minutes (`_WEIGHTS_CACHE_TTL_SEC`); recomputed lazily on the next `arbitrate_node` call after expiry.
- Returns the static `WEIGHTS` dict verbatim when **no** agent has evaluated history yet, or per-agent when an agent has fewer than `_MIN_EVALUATED_VOTES` (5) evaluated votes.
- Thread-safe via `_weights_lock` (threading.Lock) to prevent thundering-herd recomputation.

## Partial exits — `sell_pct` from sizing

`arbitrate_node` derives the SELL exit percentage from the risk manager's
`sizing_recommendation`, mapped via `SIZING_TO_SELL_PCT`:

| `sizing_recommendation` | `sell_pct` |
|-------------------------|-----------:|
| `FULL` | 100 |
| `HALF` | 50 |
| `QUARTER` | 25 |
| `SKIP` | 0 |

The technician may also propose its own `sell_pct`; the final value is
`min(risk_pct, tech_pct)`. A `sell_pct` of 0 fails `risk_check_node`
(`0 < sell_pct <= 100`) so the trade is skipped instead of executed.

## Deferred `was_correct` evaluation

`agent_memory.was_correct` is no longer set by `arbitrate_node` (which was
tautological — it just measured consensus). The new pipeline:

1. `save_memory_node` inserts a `pending_evaluations` row alongside the trade
   (`evaluated=0`, `eval_after_date = entry_date + EVAL_HORIZON_CALENDAR_DAYS`,
   default 7 calendar days ≈ 5 trading days).
2. The postmortem thread calls `evaluate_pending_trades(now)` (from `agents/shared/eval.py`) every 60 s
   (skipped in SIM, runs in LIVE and PAPER).
3. For each due row, `_fast_last_price(symbol)` in `eval.py` queries `yfinance.Ticker.fast_info`.
   The verdict for every `agent_memory` row sharing that `trace_id`:
   - **BUY**: `was_correct=1` if price moved up by more than `EVAL_SIGNIFICANCE_PCT`
     (1 %), `0` if it moved down by more than 1 %, `NULL` otherwise (inconclusive).
   - **SELL**: symmetric.
4. Pending rows are flagged `evaluated=1` even when inconclusive (anti-retry
   loop). Only `_fast_last_price → None` keeps a row `evaluated=0` for a
   later retry.

## Runtime modes (LIVE / PAPER / SIM)

Three mutually-exclusive modes — the active one is exposed as `_ctrl["mode"]`
and on the `/health` endpoint:

| Mode | Prices | Decisions | DB | Cycle | LLM cost |
|------|--------|-----------|----|-------|----------|
| `LIVE` | yfinance real-time | LLM (Sonnet + Haiku + web_search) | `trades.db` | `AGENT_INTERVAL` (30 s) | $$$ |
| `PAPER` | yfinance real-time | Rule-based (`sim_*` nodes) — zero LLM | `trades_paper.db` | `AGENT_INTERVAL` (30 s) | 0 |
| `SIM` | Random walk | Rule-based (`sim_*` nodes) | `trades_sim.db` | 3 s (fast) | 0 |

Wiring (no separate graph builder — the same compiled graph is used in all
three modes; the routing happens inside each node):

- `_no_llm_mode()` returns `True` for SIM **or** PAPER. Every Anthropic call
  site (`research_node`, `load_memory_node`, `save_memory_node`, the four
  specialist nodes, `supervisor_node`, `arbitrate_node`, postmortem summary)
  is gated by this helper and falls back to its `sim_*` rule-based variant.
- `fetch_data_node` is the only node that distinguishes PAPER from SIM:
  it uses the live yfinance branch in PAPER (and LIVE), and `sim_fetch_data`
  in SIM only.
- Toggles `set_simulation_mode()` / `set_paper_mode()` enforce mutual
  exclusion and persist `SIMULATION_MODE` / `PAPER_MODE` to `.env`.
- The React frontend's topbar mode selector calls
  `POST /api/control/mode` (`api/routes/control.py`), which invokes the
  same setters.

## StateGraph — Nodes & Edges

### Multi-agent graph (`agents/multi.py`) — unique graph

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

Shared nodes are implemented in `agents/shared/nodes.py` (with SQLite in `agents/shared/db.py`, `_llm` in `agents/shared/llm.py`, deferred evaluation in `agents/shared/eval.py`) and reused by `agents/multi.py`: `load_memory`, `fetch_data`, `risk_check`, `execute`, `save_memory`, `skip`, `research`.

`agents/registry.py` exposes a single `get_graph(portfolio)` returning the compiled multi-agent graph and `get_graph_info()` returning UI metadata. It lives in `agents/` because it imports `agents.multi` — `core/` must never depend on `agents/`.

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
    source                TEXT DEFAULT 'live',  -- 'live' | 'paper' | 'simulation'
    sell_pct              REAL                  -- NULL for BUY, 0–100 for SELL
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
    was_correct  INTEGER,        -- NULL until evaluate_pending_trades resolves it
    lesson       TEXT,
    source       TEXT DEFAULT 'simulation'
);

CREATE TABLE pending_evaluations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        INTEGER NOT NULL,
    trace_id        TEXT,
    symbol          TEXT NOT NULL,
    action          TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    entry_date      TEXT NOT NULL,
    eval_after_date TEXT NOT NULL,
    evaluated       INTEGER DEFAULT 0
);
CREATE INDEX idx_pending_eval_due
    ON pending_evaluations (evaluated, eval_after_date);

CREATE TABLE watchlist (
    symbol   TEXT PRIMARY KEY,   -- upper-case ticker; max 20 rows (enforced in code)
    added_at TEXT NOT NULL,      -- ISO-8601 UTC
    source   TEXT DEFAULT 'manual'  -- e.g. seed | manual
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

`source` values: `'live'`, `'paper'`, or `'simulation'`.
`HOLD` actions are not persisted to `trades` (save_memory_node skips HOLDs).
`agent_memory.was_correct` is set asynchronously by `evaluate_pending_trades` (postmortem thread) based on the actual market outcome after `EVAL_HORIZON_DAYS` (≈ `EVAL_HORIZON_CALENDAR_DAYS` = 7 calendar days). Only BUY/SELL votes are evaluated; HOLD votes (`risk_manager`, `macro_watcher`) remain `was_correct=NULL` so they don't pollute `_compute_dynamic_weights`.
`postmortem` rows are written once per SELL trade by `run_daily_postmortem()` at `POSTMORTEM_HOUR`.
**`watchlist`** — one row per ticker (max **20** enforced in `agents/shared/watchlist.py`). New DB files are seeded from `config.WATCHLIST`. A symbol with an **open** position cannot be removed from the watchlist.

## External data sources

| Source | Module | Usage |
|--------|--------|--------|
| **FRED** (St. Louis Fed) | `core/external_data.fetch_fred_latest`, `fetch_macro_indicators` | Terminal macro bar (e.g. Fed funds, 10Y). Optional `FRED_API_KEY` — many series work **without** a key in JSON but are **rate-limited**. |
| **CNN Fear & Greed** | `core/external_data.fetch_fear_greed` | Macro bar `F&G` cell. Endpoint is **not officially documented**; failures are **fail-silent** (`F&G: —`). |
| **Earnings calendar** | `market_data.fetch_earnings_calendar`, `build_economic_calendar_rows` | Merges yfinance `Ticker.calendar` with a static macro schedule for the terminal strip and agent context. **`calendar` format varies by yfinance version** — helpers stay in **try/except**. |

## Daily Postmortem

`run_daily_postmortem(portfolio, db_path)` in `agents/multi.py`:
- Triggered by a dedicated background thread (`apex7-postmortem`, daemon) started in `dashboard/controller.py`
- Runs at `POSTMORTEM_HOUR` (default 22:00) once per calendar day
- Scans `portfolio.trade_history` for SELL trades since midnight
- For each SELL, finds the matching BUY, computes P&L % and holding duration in hours
- Queries `agent_memory` for agents that voted SELL correctly on that symbol
- Generates a 2-sentence summary via Haiku in LIVE; rule-based string in SIM/PAPER
- Inserts one row into `postmortem` per trade

## API + React frontend

The Dash UI (server-rendered layout + `@app.callback`s) was fully removed
in favor of a FastAPI backend (`api/`) and a React 19 + Mantine 9 + Vite + TypeScript
frontend (`frontend/`). `api/main.py` is non-invasive: it reads
`dashboard.controller._state` / `_ctrl` and calls `start_controller()`
from its `lifespan` hook — zero changes to `agents/`, `core/`, or
`market_data/`.

### REST endpoints

| Route | File | Purpose |
|-------|------|---------|
| `GET /api/portfolio`, `/api/trades`, `/api/analytics` | `api/routes/portfolio.py` | Portfolio snapshot, trade history, analytics KPIs |
| `GET /api/market/macro\|watchlist\|sectors\|correlation\|sparkline/{symbol}\|news/{symbol}\|fundamentals/{symbol}\|fear-greed` | `api/routes/market.py` | Terminal tab data, thin wrappers over `market_data/` |
| `POST /api/control/mode\|pause\|resume`, `GET/POST /api/control/watchlist*` | `api/routes/control.py` | Mode toggle, pause/resume, watchlist CRUD |
| `GET /ws` | `api/routes/ws.py` | WebSocket — `api/broadcaster.py` polls `_state` every 500ms and pushes JSON snapshots + agent-vote diffs |
| `GET /health` | `api/main.py` | 200 when alive, **503** when the portfolio is dead or missing (same contract the old Dash `/health` had) |

All REST routes and the WebSocket require Bearer-token auth when
`DASHBOARD_PASSWORD` is set (`api/auth.py`); unset = no auth (localhost
default). `/health` is always open for monitoring probes.

### Frontend (`frontend/src/`)

React tabs mirror the old Dash tabs conceptually (Live, Terminal,
Analytics) under `components/{live,terminal,analytics}/`, driven by
`hooks/useWebSocket.ts` (snapshot + vote diffs) and `hooks/useApex.ts`
(REST polling: watchlist 10s, macro 60s, sectors 60s, correlation 120s).
See `frontend/src/` for the current component tree.

## Data Classes

### `Portfolio` (`data.py`)

Thread-safe portfolio state. All mutations protected by `threading.RLock()`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `cash` | float | Available cash |
| `positions` | dict | `{symbol: {shares, avg_price, layers}}` — successive BUYs on the same symbol **pyramid** up to ``MAX_PYRAMID_LAYERS``; each add recomputes `avg_price` as share-weighted average \((\text{old\_shares} \cdot \text{old\_avg} + \text{new\_shares} \cdot \text{price}) / \text{total\_shares}\) |
| `trade_history` | list | All executed trades (in-memory) |
| `value_history` | list | `[{time, value}]` snapshots |
| `agent_log` | list | `[{time, message, level}]` |
| `is_dead` | bool | True when total value < DEATH_THRESHOLD |
| `last_prices` | dict | Last fetched prices cache |
| `peak_value` | float | All-time peak portfolio value (updated in `record_value`) |
| `high_watermarks` | dict | Per-symbol peak price for **trailing** stop — initialized on **first** BUY only; **not** reset when pyramiding |

Key methods:

| Method | Description |
|--------|-------------|
| `buy(symbol, amount_usd, price)` | New position or **pyramid** add. Fails when `layers` ≥ `MAX_PYRAMID_LAYERS`. Weighted `avg_price`; `high_watermarks[sym]` set only on **initial** open. |
| `sell(symbol, sell_pct, price)` | Closes or reduces position |
| `open_symbols()` | Returns list of currently held symbols |
| `closed_trades_since(ts)` | Returns SELL trades from `trade_history` with `time >= ts` |
| `fetch_prices(symbols)` | Fetches live prices via `yf.Tickers` fast_info |
| `total_value(prices)` | Cash + sum of position values |
| `record_value(prices)` | Appends snapshot to `value_history`; updates `peak_value` |
| `update_watermarks(prices)` | Bumps `high_watermarks` toward current quotes (trailing SL) |
| `check_death(prices)` | Sets `is_dead = True` if total value < DEATH_THRESHOLD |
| `save_state(path)` | Serializes cash/positions/history/peak_value to JSON |
| `load_state(path)` | Restores state from JSON (no-op if file absent) |

### Historical backtest (`backtest.py`)

No LLM calls — deterministic rules on real yfinance OHLCV data.

```python
from core.backtest import fetch_historical, compute_indicators, run_backtest, compare_strategies

df = fetch_historical("AAPL", period="6mo", interval="1d")  # yfinance OHLCV DataFrame
df = compute_indicators(df)   # adds RSI_14, MA_20, MA_50, MACD, BB_upper, BB_lower
result = run_backtest("AAPL", strategy="simple", period="6mo", initial_cash=1000.0, stop_loss_pct=0.05)
# result keys: symbol, period, strategy, trades, final_value, total_return_pct,
#              win_rate, max_drawdown_pct, sharpe_ratio, n_trades,
#              benchmark_return_pct, vs_benchmark, equity_curve
both = compare_strategies("AAPL", period="6mo")  # runs both "simple" and "multi"
```

Strategies: `"simple"` (RSI<30 → BUY, RSI>70 → SELL), `"multi"` (same + simulated majority vote TECH+ANLST).

### `LiveFeed` (`data.py`)

Fetches 1-minute interval prices for one or more symbols via yfinance.

```python
feed = LiveFeed(["AAPL", "MSFT"])
prices = feed.fetch()  # -> {"AAPL": 185.0, "MSFT": 415.0}
```

Wired into `Portfolio.fetch_prices()` when `USE_LIVEFEED=True`. If `LiveFeed.fetch()` raises or returns empty, `Portfolio.fetch_prices()` falls back to `yf.Tickers` fast_info silently. The `LiveFeed` instance is created lazily once per `Portfolio` instance.

## Discord notifications (`core/notifications.py`)

Optional `DISCORD_WEBHOOK_URL` — same **`httpx.post`**, 5s timeout, **fail-silent** pattern for all message types.

| Alert | Entry point | Trigger |
|-------|-------------|---------|
| Trade / death / stagnation / rate-limit / startup | Various wire sites in `agents`, `dashboard`, `llm` | Existing sprint v2 behavior |
| **Daily digest** | `alert_daily_digest` ← `run_daily_digest` | Same **postmortem hour** gate as `run_daily_postmortem` (`POSTMORTEM_HOUR`), once per calendar day |
| **Weekly report** | `alert_weekly_report` ← `run_weekly_report` | **Sunday** at that hour, after digest/scheduling (`dashboard/controller.py` `_run_digest_and_weekly_at_postmortem_hour`) |
| **Evaluation** | `alert_evaluation` | Emitted from `evaluate_pending_trades` when a pending trade is scored (`was_correct` resolved) |

## Concurrency Model

- API request thread (`api/routes/*.py`, `api/broadcaster.py`): reads `_state["portfolio"]` — no mutations
- Agent loop thread (`apex7-agent`, daemon): mutates Portfolio via `buy()`, `sell()`, `record_value()` — launched by `start_controller()` in `dashboard/controller.py`
- Postmortem thread (`apex7-postmortem`, daemon): runs every 60 s; calls `evaluate_pending_trades(now)` to resolve due `was_correct` rows in LIVE/PAPER (skipped in SIM), and `run_daily_postmortem()` once per day at `POSTMORTEM_HOUR`. **Same hour** also runs `run_daily_digest()` and, on **Sundays**, `run_weekly_report()` (`_run_digest_and_weekly_at_postmortem_hour`). Reads `portfolio.trade_history`, writes to SQLite — no Portfolio mutations.
- All Portfolio mutations use `with self._lock` (RLock)
- SQLite writes go through `_db_write()` in `agents/shared/db.py` (re-exported from `agents.shared.nodes`) — handles WAL mode, retries (3 attempts with backoff), and structured logging
- Sim and live use separate databases (`trades_sim.db` / `trades.db`) via `_get_db_path()`
- `_ctrl` and `_state` in `dashboard/controller.py` share one **`threading.RLock()`** (`_controller_lock`) — all mutations and reads use `with _controller_lock`.
- Reset: agent thread is stopped (`portfolio.is_dead = True`), new Portfolio + thread created

## `market_data/` — Standalone Market Data Package

Zero imports from `agents/` or `dashboard/`. Public API: ``from market_data import …`` (voir ``__init__.py``). Implémentation par sous-modules : ``macro``, ``quotes``, ``news``, ``earnings``, ``charts``, ``sectors``, ``correlation``, ``economic_calendar``, ``screener`` ; caches partagés dans ``caches.py`` ; ``compat.py`` expose ``yfinance`` pour les tests (``patch market_data.yf``). Utilisé surtout par ``api/routes/market.py``.

| Function | Cache TTL | Description |
|----------|-----------|-------------|
| `fetch_macro()` | 60s | Fetches VIX (`^VIX`), SPY, DXY (`DX-Y.NYB`) via yfinance; returns price, change_pct, direction; fallback to last known value on error |
| `fetch_watchlist_prices(symbols)` | 10s | Per-symbol: price, change_pct, change_abs, volume, high_52w, low_52w, rsi_14 (14-day daily close), above_ma20 (bool) |
| `fetch_news(symbol, max_items)` | none | Uses `yf.Ticker.news`; returns title, source, age ("Xm/Xh/Xd ago"), url, sentiment (positive/negative/neutral via keyword rule) |
| `run_screener(symbols, filters)` | n/a | Reuses `fetch_watchlist_prices()`; filters: rsi_min/max, change_pct_min, above_ma20, volume_min; returns list of passing symbols |
| `fetch_sparkline(symbol)` | 5 min | 1-day hourly OHLC via yfinance; returns `[{"time": "14:00", "price": 182.5, "open": 181.0}, ...]`; empty list on failure |
| `fetch_comparison(symbols, period)` | 5 min | Daily closes normalized to 100.0 at first point; returns `{"AAPL": [{"date": "...", "value": 100.0}, ...], ...}`; empty dict on failure |
| `fetch_ohlcv(symbol, period)` | 5 min per `(symbol, period)` | Daily OHLCV; returns `[{"date": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]`; empty list on failure; never raises |
| `fetch_sector_performance(periods)` | per-sector TTL cache | Sector ETF % change grid (`yf.download`); cells `None` on failure |
| `fetch_correlation_matrix(symbols, period)` | matrix cache | Pearson correlation of daily **returns**; needs ≥ 2 symbols; handles yfinance **MultiIndex** columns |
| `fetch_earnings_calendar(symbols)` | **5 min** (`_EARNINGS_TTL`) per sorted symbol-set | Next earnings date per symbol via `Ticker.calendar`; **try/except**; shared cache for `is_earnings_week` |
| `is_earnings_week(symbol)` | uses earnings cache | `True` if next earnings within 5 calendar days |
| `build_economic_calendar_rows(symbols, …)` | n/a | Merges earnings rows with static **FOMC/CPI/NFP** schedule (`_SCHEDULED_MACRO_EVENTS`); logs **warning** if that schedule is stale (last event date in the past) |

Cache uses `threading.Lock()` in ``market_data/caches.py`` — thread-safe for concurrent API requests.

## CI/CD Pipeline

```
push / PR to master
        │
        ▼
  GitHub Actions (.github/workflows/ci.yml)
        │
        ├── job: test (ubuntu-latest, matrix: py3.12/3.13)
        │     ├── uv python install
        │     ├── uv sync
        │     ├── ruff check . --select E,F,W --ignore E501
        │     └── pytest tests/ -v --tb=short --cov=. --cov-fail-under=60   (SIMULATION_MODE=true)
        │
        ├── job: lint (ubuntu-latest)
        │     ├── uv sync
        │     └── black --check --diff .
        │
        ├── job: security (ubuntu-latest)
        │     ├── uv sync
        │     └── ruff check . --select S --ignore S110,S311,S104 --exclude tests
        │
        └── job: frontend (ubuntu-latest, working-directory: frontend)
              ├── npm ci
              ├── tsc --noEmit
              ├── npm test
              └── npm run build
```

Pre-commit hooks (`.pre-commit-config.yaml`): ruff (auto-fix) + black + trailing-whitespace + end-of-file-fixer + check-yaml + check-json + check-merge-conflict.

## Configuration

| Constant | Source | Default | Effect |
|----------|--------|---------|--------|
| `ANTHROPIC_API_KEY` | env | — | Required for live mode |
| `SIMULATION_MODE` | env | `false` | Random-walk prices + rule-based decisions + `trades_sim.db` |
| `PAPER_MODE` | env | `false` | Real prices + rule-based decisions + `trades_paper.db` (mutually exclusive with SIMULATION_MODE) |
| `EVAL_HORIZON_DAYS` | hardcoded | `5` | Trading-day target for ``was_correct`` evaluation |
| `EVAL_HORIZON_CALENDAR_DAYS` | hardcoded | `7` | Calendar-day approximation for `pending_evaluations.eval_after_date` |
| `SIM_VOLATILITY` | env | `0.02` | Price random-walk std dev per step |
| `SIM_DRIFT` | env | `0.0001` | Price drift per step |
| `X_BEARER_TOKEN` | env | — | Twitter/X sentiment (optional) |
| `MACRO_SYMBOLS` | hardcoded | `{"VIX": "^VIX", "SPY": "SPY", "DXY": "DX-Y.NYB"}` | Symbols fetched for TERMINAL macro bar |
| `MARKET_DATA_CACHE_SEC` | hardcoded | `60` | Macro cache TTL (`market_data.caches` / `macro.py`) |
| `WATCHLIST_CACHE_SEC` | hardcoded | `10` | Watchlist prices cache TTL (`market_data.caches` / `quotes.py`) |
| `NEWS_MAX_ITEMS` | hardcoded | `8` | Max news items from `fetch_news()` |
| `STOP_LOSS_PCT` | hardcoded | `0.05` | Stop-loss threshold (5%) — enforced as a pre-check loop in `execute_node` before the agent decision |
| `POSTMORTEM_HOUR` | hardcoded | `22` | Hour (0–23) at which daily postmortem runs |
| `WATCHLIST` | hardcoded | 5 tickers | AAPL, MSFT, GOOG, AMZN, TSLA |
| `INITIAL_BALANCE` | hardcoded | `1000` | Starting cash |
| `DEATH_THRESHOLD` | hardcoded | `50.0` | Portfolio floor |
| `MAX_POSITIONS` | hardcoded | `3` | Max simultaneous positions |
| `MAX_ALLOC_PCT` | hardcoded | `40` | Max % portfolio per trade |
| `DISCORD_WEBHOOK_URL` | env | — | Optional — trades, stagnation, death, rate-limit, startup, **daily digest**, **weekly report**, **evaluation** |
| `FRED_API_KEY` | env | — | Optional FRED key; keyless JSON often works but is rate-limited (`core/external_data`) |
| `MAX_PYRAMID_LAYERS` | env | `3` | Max pyramid BUY layers per symbol |
| `AGENT_INTERVAL` | hardcoded | `30` | Seconds between live cycles (3s in sim) |
