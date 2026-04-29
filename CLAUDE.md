# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the dashboard + agent (opens http://localhost:8050)
uv run python main.py

# Run a single agent cycle standalone (calls Anthropic + yfinance)
uv run python agents/simple.py

# Launch LangGraph Studio (visual graph debugger)
uv run langgraph dev

# Run regression smoke tests (11 tests, legacy runner: assert+print; or pytest: uv run pytest tests/test_smoke.py -q)
uv run python tests/test_smoke.py

# Run terminal/market data tests (7 tests, no pytest)
uv run python tests/test_terminal.py

# Lint (CI-grade)
uv run ruff check . --select E,F,W --ignore E501

# Format check
uv run black --check .

# CI: .github/workflows/ci.yml — job "lint" = black --check only; job "test" = ruff + pytest + coverage

# Run all pre-commit hooks
uv run pre-commit run --all-files
```

## Repo Structure

```
apex7-trader/
├── main.py
├── config.py
├── market_data.py
├── leaderboard.py
├── pyproject.toml
├── langgraph.json
├── README.md             ← symlink → docs/README.md (tracked: docs/README.md)
├── agents/
│   ├── __init__.py
│   ├── simple.py          ← simple graph (was agent.py)
│   ├── multi.py           ← multi-agent graph (was agent_multi.py)
│   └── shared/
│       ├── __init__.py
│       ├── state.py       ← AgentState, MultiAgentState TypedDicts
│       ├── nodes.py       ← shared nodes (load_memory, execute, etc.)
│       ├── prompts.py     ← system prompts versionnés (PROMPT_VERSION)
│       └── schemas.py     ← Pydantic validation for LLM outputs
├── core/
│   ├── __init__.py
│   ├── data.py            ← Portfolio, LiveFeed
│   ├── backtest.py        ← BacktestEngine, run_backtest
│   ├── indicators.py      ← Shared RSI implementation
│   └── registry.py        ← graph ID → builder map
├── dashboard/
│   ├── __init__.py        ← create_app()
│   ├── server.py          ← Dash() init + design tokens
│   ├── controller.py      ← agent loop, portfolio state, postmortem thread
│   ├── layout/            ← app.layout + UI helpers (package; was layout.py)
│   │   ├── __init__.py
│   │   ├── main.py        ← setup_layout(), assigns app.layout
│   │   ├── live_tab.py
│   │   ├── analytics_tab.py
│   │   ├── terminal_tab.py
│   │   ├── helpers.py
│   │   ├── classify.py
│   │   └── emotions.py
│   └── callbacks/
│       ├── __init__.py    ← imports all callback modules
│       ├── live.py        ← live tab + tab routing
│       ├── analytics.py   ← analytics tab
│       ├── backtest_tab.py← backtest tab
│       ├── leaderboard_tab.py ← leaderboard tab
│       ├── heatmap.py     ← heatmap tab
│       ├── agents.py      ← agents tab
│       └── terminal.py    ← terminal tab (16 callbacks)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CHANGELOG.md
│   └── README.md
└── tests/
    ├── conftest.py
    ├── test_circuit_breaker.py
    ├── test_integration.py
    ├── test_layout_helpers.py
    ├── test_misc_coverage.py
    ├── test_portfolio.py
    ├── test_smoke.py
    ├── test_stoploss.py
    ├── test_terminal.py
```

**File ownership:**
- `agents/` — apex7-senior-back
- `core/` — apex7-senior-back
- `dashboard/` — apex7-senior-front
- `config.py`, `leaderboard.py`, `market_data.py` — apex7-senior-back

## Architecture

APEX-7 is a survival trading agent that starts with $1,000 and dies if the portfolio drops below $50. It runs as a background thread behind a Dash dashboard.

### Key files

| File | Role |
|------|------|
| `main.py` | Entrypoint — calls `create_app().run()` |
| `dashboard/controller.py` | Agent loop thread, portfolio init, postmortem thread |
| `dashboard/layout/` | Dash layout package — `main.py` sets `app.layout`; tab modules + helpers |
| `dashboard/callbacks/` | All `@app.callback` handlers (7 modules) |
| `agents/simple.py` | Simple graph: LangGraph nodes, simulation engine, `start_agent()` |
| `agents/multi.py` | Multi-agent graph: 4 specialized agents + arbitration node + `run_daily_postmortem()` |
| `agents/shared/state.py` | `AgentState`, `MultiAgentState` TypedDicts |
| `agents/shared/nodes.py` | Shared nodes: `load_memory`, `fetch_data`, `risk_check`, `execute`, `save_memory`, `skip`, `research`; also `_llm()` helper, `_db_write()`, simulation engine |
| `agents/shared/schemas.py` | Pydantic validation models for LLM decision outputs |
| `core/data.py` | `Portfolio` — thread-safe state; `LiveFeed` — multi-symbol yfinance wrapper |
| `core/backtest.py` | `BacktestEngine` + functional API (`run_backtest`, `compare_strategies`) |
| `core/indicators.py` | Shared `rsi()` implementation used across agents, backtest, and market_data |
| `core/registry.py` | Graph ID → builder map |
| `config.py` | All constants, loaded from `.env` |
| `market_data.py` | Standalone market data — fetch_macro, fetch_watchlist_prices, fetch_news, run_screener, fetch_sparkline, fetch_comparison |
| `langgraph.json` | LangGraph Studio config — exposes both compiled graphs |
| `tests/test_smoke.py` | 11 regression smoke tests — no pytest, assert+print, exit 0/1 |
| `tests/test_terminal.py` | 7 market data tests (sparkline, comparison, screener, cache) |
| `tests/test_integration.py` | pytest integration tests with mocked LLM (sim mode) |

### Concurrency model

The Dash callback thread and the agent loop thread share a single `Portfolio` object. All mutations on `Portfolio` are protected by `threading.RLock()`. The agent's `AgentState` is a per-cycle snapshot; `Portfolio` is the source of truth for the dashboard.

A third daemon thread (`apex7-postmortem`) runs in `dashboard/controller.py` and calls `run_daily_postmortem()` once per day at `POSTMORTEM_HOUR`. It only reads `portfolio.trade_history` and writes to SQLite — no Portfolio mutations.

### Two graphs

**Simple graph** (`AGENT_GRAPH=simple`, default):
```
load_memory → fetch_data → analyze → [research loop if conf < 0.70] → risk_check → execute → save_memory
```

**Multi-agent graph** (`AGENT_GRAPH=multi`):
```
load_memory → fetch_data → supervisor → [technician | analyst | risk_manager | macro_watcher] (parallel, via Send) → arbitrate → [research if conf < 0.72] → risk_check → execute → save_memory
```

Nodes shared between both graphs: `load_memory`, `fetch_data`, `risk_check`, `execute`, `save_memory`, `skip`, `research` (defined in `agents/shared/nodes.py`).

### Model usage

- `claude-sonnet-4-5` — `analyze_node`, `analyst_node`, `arbitrate_node` (complex reasoning + web search)
- `claude-haiku-4-5-20251001` — `load_memory_node` (pattern extraction), `save_memory_node` (lesson generation), `technician_node`, `risk_manager_node`, `macro_watcher_node`, `supervisor_node`

The `_llm()` helper in `agents/shared/nodes.py` handles the agentic web-search tool loop (up to 8 iterations) using Claude's `web_search_20250305` tool directly via the Anthropic SDK. It includes a daily token budget cap and circuit breaker (3 consecutive failures → 5-minute pause). On `anthropic.RateLimitError`, the breaker opens immediately so later `_llm()` calls respect `Retry-After` / pause.

### Simulation mode

When `SIMULATION_MODE=true` (or toggled live from the Dash UI):
- `sim_fetch_data()` / `sim_analyze()` replace real data fetches and LLM calls with a random-walk price engine and RSI-based rule logic
- No Anthropic API calls are made; trades are recorded in `trades_sim.db` (separate from `trades.db`) with `source='simulation'`
- Cycle interval drops from `AGENT_INTERVAL` (30s) to 3s
- The mode switch takes effect on the next cycle with no restart
- `_get_db_path()` returns `trades_sim.db` in sim mode, `trades.db` in live mode

### State accumulation pattern

`AgentState` uses `Annotated[List, operator.add]` for `log` and `portfolio_history` fields so nodes can append without overwriting. Nodes return only the fields they modify.

### LLM output validation

All LLM JSON outputs are validated through Pydantic models in `agents/shared/schemas.py`:

| Model | Used by | Key validations |
|-------|---------|-----------------|
| `DecisionOutput` | `analyze_node`, `arbitrate_node` | action, confidence, allocation_pct, emotion, symbol |
| `TechVote` | `technician_node` | action, confidence, allocation_pct, key_indicators |
| `AnalystVote` | `analyst_node` | action, confidence, catalysts, sentiment_score |
| `RiskVote` | `risk_manager_node` | risk_score [0-10], sizing_recommendation, var_1d |
| `MacroVote` | `macro_watcher_node` | market_regime, macro_bias, macro_score [-1,1] |

Shared validators via `_ActionConfidenceMixin`:
- `action` must be `BUY`, `SELL`, or `HOLD` (defaults to `HOLD`)
- `confidence` is clamped to [0.0, 1.0] (values > 1.0 are divided by 100)
- `allocation_pct` is clamped to [0, 100]

If validation fails entirely, each `validate_*()` function returns safe defaults (HOLD, 0.5 confidence).

### LLM prompts

System prompts and user messages in `analyze_node`, `research_node`, and the multi-agent nodes are written in French. This is intentional — do not translate them.

### Adding a new graph node

```python
# In agents/simple.py
def my_node(state: AgentState) -> dict:
    return {"log": [_entry("my_node ran")], "confidence": 0.9}

g.add_node("my_node", my_node)
g.add_edge("analyze", "my_node")
g.add_edge("my_node", "risk_check")
```

### SQLite schema

`trades.db` (live) and `trades_sim.db` (simulation) are auto-created on first access via `_ensure_db()` with WAL mode and busy_timeout=5000ms. Four tables:

| Table | Description |
|-------|-------------|
| `trades` | One row per executed BUY/SELL trade (HOLD not persisted); includes `trace_id` (agent cycle) and `source` |
| `patterns` | Lessons extracted by Haiku after each trade |
| `agent_memory` | One row per agent vote per cycle; `was_correct` updated by `arbitrate_node` |
| `postmortem` | One row per closed trade (SELL); written by `run_daily_postmortem()` |

The `source` column on `trades`, `agent_memory`, and `postmortem` is `'live'` or `'simulation'`.

All SQLite writes go through `_db_write()` / `_db_write_multi()` in `agents/shared/nodes.py` (retries, `with closing(...)`, logging on failure). All reads go through `_db_read()` in the same module: it uses `_get_db_path()` for sim vs live, triggers `_ensure_db()`, sets `PRAGMA busy_timeout=5000` per connection, and retries on lock contention — used by agent nodes, `dashboard/layout/helpers.py` (`_load_trades_db`, `_load_agent_memory`, `_load_postmortem`), and the live tab track-records block in `dashboard/callbacks/live.py`.

### LiveFeed

`LiveFeed` in `core/data.py` provides multi-symbol price fetching using 1m yfinance history. Wired into `Portfolio.fetch_prices()` when `USE_LIVEFEED=True`. Falls back to `yf.Tickers` fast_info silently on error.

## Configuration

All tuneable constants are in `config.py`. Env vars override at startup:

| Env var | Default | Effect |
|---------|---------|--------|
| `ANTHROPIC_API_KEY` | — | Required for live mode |
| `SIMULATION_MODE` | `false` | Skip all network/LLM calls |
| `SIM_VOLATILITY` | `0.02` | Price random-walk std dev per step |
| `SIM_DRIFT` | `0.0001` | Price drift per step |
| `AGENT_GRAPH` | `simple` | `simple` or `multi` |
| `X_BEARER_TOKEN` | — | Twitter/X sentiment (optional) |
| `USE_LIVEFEED` | `true` | Delegate Portfolio.fetch_prices() to LiveFeed; set `false` in tests |
| `PORTFOLIO_STATE_PATH` | `portfolio_state.json` | Path for JSON portfolio persistence |
| `PORTFOLIO_SAVE_ENABLED` | `true` | Enable/disable Portfolio save_state(); set `false` in unit tests |
| `MACRO_SYMBOLS` | `{"VIX": "^VIX", "SPY": "SPY", "DXY": "DX-Y.NYB"}` | Symbols for the TERMINAL macro header bar |
| `MARKET_DATA_CACHE_SEC` | `60` | TTL for macro data cache in `market_data.py` |
| `WATCHLIST_CACHE_SEC` | `10` | TTL for watchlist prices cache in `market_data.py` |
| `NEWS_MAX_ITEMS` | `8` | Max news items returned by `fetch_news()` |

`WATCHLIST`, `INITIAL_BALANCE`, `DEATH_THRESHOLD`, `MAX_POSITIONS`, `MAX_ALLOC_PCT`, `AGENT_INTERVAL`, `STOP_LOSS_PCT`, and `POSTMORTEM_HOUR` are hardcoded in `config.py` and not overridable by env vars.

## Known pitfalls

- **CI jobs** — `.github/workflows/ci.yml`: job `lint` runs `uv run black --check .` only; job `test` runs ruff + pytest + coverage. Failing `lint` on push: reproduce with `uv run black --check --diff .`.
- **`README.md`** — root `README.md` is a symlink to `docs/README.md`; commit `docs/README.md` when updating user-facing README.
- **`_init_db()` test DB path** — if `_get_db_path()` is not the repo `trades.db` / `trades_sim.db` (e.g. `tmp_db` monkeypatch), `_init_db()` initializes only that file — avoids writing project DBs during tests.
- **GitHub MCP** — typically no Actions run logs; debug CI with the same `uv run` commands locally.
- **yfinance MultiIndex** — depuis yfinance 0.2.38+, `yf.download()` peut retourner un DataFrame en colonnes MultiIndex. Toujours passer `auto_adjust=True` ou aplatir avec `df.columns = df.columns.get_level_values(0)` avant d’accéder à `df["Close"]` (voir `_seed_live_price_history`).
- **`_seed_live_price_history` bloque `fetch_data_node`** — au premier cycle live, le téléchargement ~1 mois par symbole prend ~2–5 s chacun. Le seed est protégé par `_live_price_history_lock` pour éviter un double seed en fan-out (multi-agent).
- **No `assets/` directory** — all CSS is inlined in `dashboard/server.py`'s `index_string`. Do not create an `assets/` folder expecting Dash to pick it up automatically.
- **`HOLD` trades not saved** — `save_memory_node` returns early on HOLD. Patterns table only contains BUY/SELL lessons.
- **`avg_price` vs `avg_cost`** — both keys appear in `_portfolio_value()` due to backward compat (`pos.get("avg_price", pos.get("avg_cost", 0))`). New positions always use `avg_price`.
- **`trades.db` soft migration** — on startup, `agents/shared/nodes.py` tries `ALTER TABLE trades ADD COLUMN source …` and `ADD COLUMN trace_id …`, and silently catches `OperationalError` if columns exist. Do not remove these blocks.
- **`research` in multi-graph goes directly to `risk_check`** — unlike the simple graph where `research` loops back to `analyze`. This is intentional.
- **`LiveFeed` not wired into graph nodes** — `LiveFeed` is wired into `Portfolio.fetch_prices()` only; it is not a LangGraph node.
- **`core/registry.py` description** — update the "4 Specialists" description string if a 5th specialist is added to `agents/multi.py`.
- **`start_agent()` in `agents/simple.py` is unused from the dashboard** — `dashboard/controller.py` runs its own `_agent_loop` directly. The function exists for standalone use.
- **Postmortem thread only in `dashboard/controller.py`** — `run_daily_postmortem()` is never called from `main.py` or `agents/simple.py`. It only runs when the full Dash app is started.
- **`agent_memory` inserts in live path only for specialist nodes** — the simple graph does not write to `agent_memory` at all.
- **Multi-symbol position limit** — `Portfolio.buy()` returns `{"success": False, "error": "position already open"}` if the symbol is already held. Callers in `execute_node` check `result["success"]`.
- **`market_data.py` cache** — macro cached 60s, watchlist 10s to avoid yfinance rate limiting. Cache is in-memory only; resets on restart.
- **`market_data.py` decoupled** — zero imports from `agents/` or `dashboard/` by design.
- **`USE_LIVEFEED=False` in tests** — set via env or config override to avoid yfinance rate limiting during test runs.
- **`portfolio_state.json` created on first run** — added to `.gitignore`, do not commit.
- **`PORTFOLIO_SAVE_ENABLED=True` by default** — set to `False` in unit tests to avoid disk writes.
- **`dashboard/callbacks/__init__.py` must import all callback modules** — `live`, `analytics`, `backtest_tab`, `leaderboard_tab`, `heatmap`, `agents`, `terminal` must all be imported. If any are missing, those `@app.callback` decorators are never registered and the corresponding UI updates silently fail.
- **`agents/` → `dashboard/` import direction is forbidden** — `agents/shared/nodes.py` imports from `core.data`. Never import from `dashboard` in any `agents/` file. This violates the one-way dependency rule (dashboard depends on agents/core, not the reverse).
- **Lazy DB init** — `_init_db()` is no longer called at import time. It runs lazily on first `_db_write`/`_db_read`/`_db_write_multi` call via `_ensure_db()`. Importing `agents/shared/nodes.py` no longer creates SQLite tables. Importing `dashboard/controller.py` does not create a `Portfolio` until `start_controller()` is called explicitly. Importing `agents/simple.py` or `agents/multi.py` compiles a LangGraph graph at module level (for LangGraph Studio compatibility).
- **RSI computed in `core/indicators.py`** — a single canonical `rsi()` function. Do not re-implement RSI elsewhere.
- **`_db_write()` / `_db_read()` centralize all SQLite access** — never open raw `sqlite3.connect()` anywhere — not in agent nodes, not in `dashboard/layout/helpers.py`, not in `dashboard/callbacks/`. Always use `_db_write()` or `_db_read()` from `agents.shared.nodes` (dashboard loaders and track records use `_db_read()` so analytics match sim/live mode).
- **\_live\_price\_history warm-up** — en live mode, le RSI retourne 50.0 (`insufficient data`) pendant les 14 premiers cycles (~7 min) si la série n’est pas encore prête. Le technician est aveugle pendant cette période (mitigation : seed daily + append par jour, sprint v3).
- **Live mode `technician_node` RSI** — Live closes are appended in `fetch_data_node` (live path) to `_live_price_history` in `agents/shared/nodes.py` (last 100 per symbol). The multi-agent `technician_node` uses that series for RSI; simulation still uses `_sim_price_history` from `_sim_step_prices()`.
- **`_route_risk` fail-closed** — `_route_risk` defaults `_risk_passed` to `False` (fail-closed). If `risk_check_node` fails to write `_risk_passed`, the graph skips execution instead of proceeding.
- **`/health` and agent liveness** — `dashboard/server.py` returns HTTP **503** when `portfolio.is_dead` (or no portfolio), **200** when alive; JSON includes `status` (`ok` / `dead`) and `agent_alive`.
- **Zero-price stop-loss** — `execute_node` runs SL only when `sl_avg > 0`, `sl_price > 0`, and the quote is plausible: `sl_price > 1.0`, or both cost basis and quote are ≤ $1 (penny stocks). Otherwise it skips SL and logs a warning (`Skipping stop-loss check…`) — avoids bogus ticks (e.g. yfinance 0 / stale sub-dollar quote vs a normal-cost basis) without spamming every cycle on legitimate sub-dollar names.
- **Backtest vs live RSI** — `core/backtest.py` `compute_indicators()` uses `core.indicators.rsi()` for `RSI_14` (same function as agents). Do not reintroduce pandas EWM for RSI.
- **`test_sqlite_schema` fails on a clean clone** — `tests/test_smoke.py` asserts `trades.db` exists, but `_ensure_db()` is lazy and only runs on first write. The test must call `_ensure_db()` before asserting the schema.
- **Token budget resets daily** — `_maybe_reset_token_counter()` is called at the start of each `_llm()` invocation and resets `_token_counter` at midnight. **`_maybe_reset_token_counter()` acquiert `_token_counter_lock` lui-même** — ne jamais l’appeler depuis une section déjà verrouillée par `_token_counter_lock`, sinon deadlock.
- **All LLM specialist votes validated by Pydantic** — `technician_node`, `analyst_node`, `risk_manager_node`, `macro_watcher_node` and `arbitrate_node` all pass raw LLM JSON through their respective `validate_*_vote()` / `validate_decision()` functions from `agents/shared/schemas.py`.

## Code conventions

- All CSS inline as Python dicts — no external stylesheets
- Design tokens defined in `dashboard/server.py` (BG_DEEP, GREEN, RED, etc.) — reuse them everywhere
- Dash callbacks use pattern-matching IDs `{"type": ..., "index": ...}` for agent cards
- Emotion system: `_emotion(total)` derives state from portfolio value ratio; `_EMOTIONS` dict maps to icon/color/quote
- `_classify_v2()` returns `(badge_label, color)` for every log message type — extend it when adding new node types
- All LLM outputs validated through Pydantic models in `agents/shared/schemas.py`
- Structured logging via `logging.getLogger("apex7")` — do not use bare `print()` for operational logs
