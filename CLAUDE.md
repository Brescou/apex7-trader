# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the FastAPI backend + agent (opens http://localhost:8000, serves the REST/WS API)
uv run python main.py
# For local frontend dev with hot reload, also run in frontend/: npm run dev (Vite, proxies to :8000)

# Launch LangGraph Studio (visual graph debugger)
uv run langgraph dev

# Run regression smoke tests (legacy runner: assert+print; or pytest: uv run pytest tests/test_smoke.py -q)
uv run python tests/test_smoke.py

# Run terminal/market data tests (legacy runner: no pytest)
uv run pytest tests/test_terminal.py -q
uv run python tests/test_terminal.py

# Lint (CI-grade)
uv run ruff check . --select E,F,W --ignore E501

# Format check
uv run black --check .

# CI: .github/workflows/ci.yml — jobs: "lint" (black --check), "test" (ruff + pytest + coverage),
# "security" (ruff flake8-bandit), "frontend" (tsc + vitest + vite build, working-directory: frontend)

# Run all pre-commit hooks
uv run pre-commit run --all-files

# Frontend: type check / test / build (from frontend/)
npx tsc --noEmit
npm test
npm run build
```

## Repo Structure

```
apex7-trader/
├── main.py
├── config.py
├── market_data/           ← package terminal / yfinance (pas d’import agents/ ni runtime/)
│   ├── __init__.py        ← API publique (réexporte fetch_*, yf, caches test)
│   ├── caches.py
│   ├── compat.py          ← yfinance unique (tests : patch ``market_data.yf``)
│   ├── macro.py
│   ├── quotes.py
│   ├── news.py
│   ├── earnings.py
│   ├── charts.py
│   ├── sectors.py
│   ├── correlation.py
│   ├── economic_calendar.py ← FRED-backed CPI/NFP (+static FOMC fallback)
│   ├── fundamentals.py    ← yf.Ticker.info → P/E, market cap, dividend (cache 1h)
│   ├── screener.py
│   └── helpers.py
├── pyproject.toml
├── langgraph.json
├── README.md             ← symlink → docs/README.md (tracked: docs/README.md)
├── agents/
│   ├── __init__.py
│   ├── multi.py           ← unique multi-agent graph
│   ├── registry.py        ← single graph builder + UI metadata (imports agents.multi)
│   └── shared/
│       ├── __init__.py
│       ├── state.py       ← AgentState, MultiAgentState TypedDicts
│       ├── nodes.py       ← graph nodes, fetch_data, execute, sim engine (re-exports)
│       ├── db.py          ← SQLite schema, _db_read/_db_write, _get_db_path
│       ├── modes.py       ← live/paper/sim toggles, _no_llm_mode
│       ├── llm.py         ← Anthropic clients, _llm, token budget, circuit breaker
│       ├── eval.py        ← evaluate_pending_trades, _fast_last_price
│       ├── watchlist.py   ← persisted watchlist (SQLite), max 20 symbols
│       ├── prompts.py     ← system prompts versionnés (PROMPT_VERSION)
│       └── schemas.py     ← Pydantic validation for LLM outputs
├── core/
│   ├── __init__.py
│   ├── data.py            ← Portfolio, LiveFeed
│   ├── notifications.py   ← optional Discord webhook (trades, digest, weekly, evaluation, …)
│   ├── external_data.py   ← FRED series + CNN Fear & Greed (HTTP, TTL caches)
│   ├── backtest.py        ← run_backtest, compare_strategies (yfinance history)
│   └── indicators.py      ← Shared RSI implementation
├── runtime/
│   ├── __init__.py
│   └── controller.py      ← agent loop, portfolio state, postmortem thread
├── api/                   ← FastAPI backend (REST + WebSocket)
│   ├── __init__.py
│   ├── main.py            ← FastAPI() app, lifespan hook (start_controller), /health
│   ├── auth.py            ← Bearer-token gate, active only when DASHBOARD_PASSWORD is set
│   ├── broadcaster.py     ← WebSocket broadcaster, polls runtime.controller._state
│   ├── serializers.py     ← Portfolio/trade/vote → JSON dicts
│   └── routes/
│       ├── __init__.py
│       ├── portfolio.py   ← /api/portfolio, /api/trades, /api/analytics
│       ├── market.py      ← /api/market/* (macro, watchlist, sectors, correlation, news, …)
│       ├── control.py     ← /api/control/* (mode, pause/resume, watchlist CRUD)
│       └── ws.py          ← /ws WebSocket endpoint
├── frontend/              ← React 19 + Mantine 9 + Vite + TypeScript terminal UI
│   ├── package.json
│   └── src/
│       ├── App.tsx
│       ├── components/{live,terminal,analytics,layout}/
│       ├── hooks/         ← useWebSocket.ts, useApex.ts
│       └── types/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CHANGELOG.md
│   └── README.md
├── tests/
│   ├── conftest.py
│   ├── test_api.py        ← FastAPI app + lifespan (TestClient), auth
│   ├── test_circuit_breaker.py
│   ├── test_dynamic_weights.py
│   ├── test_evaluate_pending.py
│   ├── test_integration.py
│   ├── test_layout_helpers.py  ← agents/registry.py graph builder
│   ├── test_misc_coverage.py
│   ├── test_paper_mode.py
│   ├── test_paper_trading.py
│   ├── test_partial_exits.py
│   ├── test_pending_evaluations.py
│   ├── test_portfolio.py
│   ├── test_smoke.py
│   ├── test_stoploss.py
│   ├── test_terminal.py
│   ├── test_was_correct.py
│   └── ... (see tests/ for the full list — one file per subsystem)
└── data/                       ← runtime SQLite (gitignored)
    ├── trades.db               ← live mode
    ├── trades_paper.db         ← paper mode (real prices, no LLM)
    └── trades_sim.db           ← simulation (random walk)
```

(Trades DBs actually live at the repo root, not under ``data/`` — listed
together here for clarity. ``trades_paper.db`` was added in sprint v1.)

**File ownership:**
- `agents/` — apex7-senior-back
- `core/` — apex7-senior-back
- `runtime/`, `api/` — apex7-senior-back
- `frontend/` — apex7-senior-front
- `config.py`, `market_data/` — apex7-senior-back

## Architecture

APEX-7 is a survival trading agent that starts with $1,000 and dies if the portfolio drops below $50. It runs as a background thread behind a FastAPI backend + React frontend.

### Key files

| File | Role |
|------|------|
| `main.py` | Entrypoint — runs `api.main:app` via uvicorn on port 8000 |
| `runtime/controller.py` | Agent loop thread, portfolio init, postmortem thread |
| `api/main.py` | FastAPI app; `lifespan` hook calls `start_controller()`; `/health` |
| `api/auth.py` | Bearer-token auth gate (active only when `DASHBOARD_PASSWORD` is set) |
| `api/broadcaster.py` | WebSocket broadcaster — polls `runtime.controller._state` and pushes snapshots/vote diffs |
| `api/serializers.py` | Portfolio/trade/vote → JSON dicts for REST + WS |
| `api/routes/` | `portfolio.py`, `market.py`, `control.py`, `ws.py` — see "API + React frontend" below |
| `frontend/` | React 19 + Mantine 9 + Vite + TypeScript terminal UI — Live/Terminal/Analytics tabs |
| `agents/multi.py` | Unique LangGraph: 6 specialized agents + arbitration + `run_daily_postmortem()` |
| `agents/shared/state.py` | `AgentState`, `MultiAgentState` TypedDicts |
| `agents/shared/nodes.py` | LangGraph nodes: `load_memory`, `fetch_data`, `risk_check`, `execute`, `save_memory`, `skip`, `research`; simulation price engine; re-exports from `db` / `llm` / `eval` / `modes` |
| `agents/shared/db.py` | SQLite schema, `_get_db_path`, `_ensure_db`, `_db_write` / `_db_read` |
| `agents/shared/modes.py` | `_sim_mode` / `_paper_mode`, setters, `_no_llm_mode`, `get_runtime_mode` |
| `agents/shared/llm.py` | Sonnet/Haiku clients, `_llm()`, token budget, circuit breaker, degradation flags |
| `agents/shared/eval.py` | `evaluate_pending_trades`, `_fast_last_price`, `EVAL_SIGNIFICANCE_PCT` |
| `agents/shared/schemas.py` | Pydantic validation models for LLM decision outputs |
| `agents/shared/watchlist.py` | `get_watchlist`, `add_to_watchlist`, `remove_from_watchlist` — max 20 symbols |
| `core/data.py` | `Portfolio` — thread-safe state; `LiveFeed` — multi-symbol yfinance wrapper |
| `core/notifications.py` | Optional Discord webhook — callers pass `mode` / `watchlist_summary`; must not import `agents/` |
| `core/external_data.py` | `fetch_fred_latest`, `fetch_fred_release_dates` (release schedule), `fetch_macro_indicators`, `fetch_fear_greed` (CNN) |
| `core/backtest.py` | Functional API (`fetch_historical`, `compute_indicators`, `run_backtest`, `compare_strategies`) |
| `core/indicators.py` | Canonical `rsi()`, `ema()`, `macd()`, `bollinger_bands()`, `bb_position()` — used across agents, backtest, market_data |
| `agents/registry.py` | Single `get_graph(p)` + `get_graph_info()` UI metadata (in `agents/` because it imports `agents.multi`) |
| `config.py` | All constants, loaded from `.env` |
| `market_data/` | Package terminal — `macro`, `quotes`, `news`, `earnings`, `charts`, `sectors`, `correlation`, `economic_calendar`, `screener` ; **zéro** import `agents/` ni `runtime/` |
| `langgraph.json` | LangGraph Studio config — exposes both compiled graphs |
| `tests/test_smoke.py` | 11 regression smoke tests — no pytest, assert+print, exit 0/1 |
| `tests/test_terminal.py` | Market data + terminal mocks (macro strip, sector %, correlation matrix, economic calendar) |
| `tests/test_integration.py` | pytest integration tests with mocked LLM (sim mode) |

### Concurrency model

The FastAPI request/WebSocket-broadcaster thread and the agent loop thread share a single `Portfolio` object. All mutations on `Portfolio` are protected by `threading.RLock()`. The agent's `AgentState` is a per-cycle snapshot; `Portfolio` is the source of truth for the API.

A third daemon thread (`apex7-postmortem`) runs in `runtime/controller.py` and calls `run_daily_postmortem()` once per day at `POSTMORTEM_HOUR`. It only reads `portfolio.trade_history` and writes to SQLite — no Portfolio mutations.

### Pipeline (single graph)

```
load_memory → fetch_data → supervisor → [technician | analyst | risk_manager | macro_watcher | economist | geopolitician] (parallel, via Send) → arbitrate → [research if conf < 0.72, then risk_check] → risk_check → execute|skip → save_memory
```

Shared nodes (defined in `agents/shared/nodes.py`, used by `agents/multi.py`): `load_memory`, `fetch_data`, `risk_check`, `execute`, `save_memory`, `skip`, `research`.

### Model usage

- `claude-sonnet-4-5` — `analyst_node`, `geopolitician_node`, `arbitrate_node` (complex reasoning + web search)
- `claude-haiku-4-5-20251001` — `load_memory_node` (pattern extraction), `save_memory_node` (lesson generation), `technician_node`, `risk_manager_node`, `macro_watcher_node`, `economist_node`, `supervisor_node`

The `_llm()` helper in `agents/shared/llm.py` handles the agentic web-search tool loop (up to 8 iterations) using Claude's `web_search_20250305` tool directly via the Anthropic SDK. It includes a daily token budget cap and circuit breaker (3 consecutive failures → 5-minute pause). On `anthropic.RateLimitError`, the breaker opens immediately so later `_llm()` calls respect `Retry-After` / pause.

### Runtime modes (LIVE / PAPER / SIM)

The agent can run in one of three mutually-exclusive modes, switched live
from the React frontend's topbar mode selector (`POST /api/control/mode`,
`api/routes/control.py`) or by env var on startup. Backend
helpers `set_simulation_mode()` / `set_paper_mode()` / `get_runtime_mode()`
in `agents/shared/modes.py` (re-exported from `agents/shared/nodes.py`) enforce mutual exclusion.

| Mode | Prices | Decisions | DB | Cycle | LLM cost |
|------|--------|-----------|----|-------|----------|
| `LIVE` | yfinance real-time | LLM (Sonnet + Haiku + web_search) | `trades.db` | `AGENT_INTERVAL` (90 s) | $$$ |
| `PAPER` | yfinance real-time | Rule-based (`sim_*` nodes) — **zero LLM** | `trades_paper.db` | `AGENT_INTERVAL` (90 s) | 0 |
| `SIM` | Random walk (`SIM_DRIFT`/`SIM_VOLATILITY`) | Rule-based (`sim_*` nodes) | `trades_sim.db` | 3 s (fast loop) | 0 |

Implementation details:
- `_no_llm_mode()` returns `True` for sim **or** paper. Every Anthropic-bound branch (`analyst_node`, `arbitrate_node`, `supervisor_node`, `technician_node`, `risk_manager_node`, `macro_watcher_node`, `economist_node`, `geopolitician_node`, `research_node`, `load_memory_node`, `save_memory_node`, `run_daily_postmortem`) is gated by this helper.
- `_get_db_path()` priority: `paper > sim > live` (defensive: paper wins if both flags are accidentally on).
- `source` column values: `'live'`, `'paper'`, `'simulation'`.
- Mode switch takes effect on the next cycle — no thread restart needed.
- `/health` JSON exposes `"mode": "live"|"paper"|"sim"` plus the legacy `"simulation"` boolean.

### State accumulation pattern

`AgentState` uses `Annotated[List, operator.add]` for `log` and `portfolio_history` fields so nodes can append without overwriting. Nodes return only the fields they modify.

### LLM output validation

All LLM JSON outputs are validated through Pydantic models in `agents/shared/schemas.py`:

| Model | Used by | Key validations |
|-------|---------|-----------------|
| `DecisionOutput` | `arbitrate_node` | action, confidence, allocation_pct, sell_pct, emotion, symbol |
| `TechVote` | `technician_node` | action, confidence, allocation_pct, key_indicators |
| `AnalystVote` | `analyst_node` | action, confidence, catalysts, sentiment_score |
| `RiskVote` | `risk_manager_node` | risk_score [0-10], sizing_recommendation, var_1d |
| `MacroVote` | `macro_watcher_node` | market_regime, macro_bias, macro_score [-1,1] |
| `EconomistVote` | `economist_node` | economic_regime, rate_trajectory, economic_score [-1,1] |
| `GeoPoliticianVote` | `geopolitician_node` | geopolitical_risk [0-10], geo_bias, geo_score [-1,1] |

Shared validators via `_ActionConfidenceMixin`:
- `action` must be `BUY`, `SELL`, or `HOLD` (defaults to `HOLD`)
- `confidence` is clamped to [0.0, 1.0] (values > 1.0 are divided by 100)
- `allocation_pct` is clamped to [0, 100]

If validation fails entirely, each `validate_*()` function returns safe defaults (HOLD, 0.5 confidence).

### LLM prompts

System prompts and user messages in `research_node` and the multi-agent specialist nodes are written in French. This is intentional — do not translate them.

### Adding a new graph node

```python
# In agents/multi.py
def my_node(state: AgentState) -> dict:
    return {"log": [_entry("my_node ran")], "confidence": 0.9}

g.add_node("my_node", my_node)
g.add_edge("analyze", "my_node")
g.add_edge("my_node", "risk_check")
```

### SQLite schema

`trades.db` (live), `trades_paper.db` (paper) and `trades_sim.db` (simulation) are auto-created on first access via `_ensure_db()` with WAL mode and busy_timeout=5000ms. Six core tables:

| Table | Description |
|-------|-------------|
| `trades` | One row per executed BUY/SELL trade (HOLD not persisted); includes `trace_id`, `prompt_version`, `sell_pct`, `source` |
| `patterns` | Lessons extracted by Haiku after each trade (template in sim/paper) |
| `agent_memory` | One row per agent vote per cycle; `was_correct` is **NULL until evaluated** by `evaluate_pending_trades` in `agents/shared/eval.py` (NOT by arbitration) |
| `postmortem` | One row per closed trade (SELL); written by `run_daily_postmortem()` |
| `pending_evaluations` | One row per executed trade scheduled for outcome evaluation (`eval_after_date = entry_date + EVAL_HORIZON_CALENDAR_DAYS`, default 7 calendar days) |
| `watchlist` | `symbol` PRIMARY KEY, `added_at`, `source` — seeded from `config.WATCHLIST` when empty; UI + `agents/shared/watchlist.py` enforce **max 20** symbols |

The `source` column on `trades`, `agent_memory`, and `postmortem` is one of `'live'` / `'paper'` / `'simulation'`.

### Deferred `was_correct` evaluation

`was_correct` no longer reflects arbitration consensus (which was tautological). Instead:
1. `save_memory_node` inserts a `pending_evaluations` row alongside the trade (`evaluated=0`, `eval_after_date = now + EVAL_HORIZON_CALENDAR_DAYS`).
2. `evaluate_pending_trades(now)` runs every minute from the postmortem thread (skipped in SIM since prices are random). It pulls due rows, fetches the spot price via `yfinance.Ticker.fast_info`, and writes `was_correct` to **every `agent_memory` row sharing the trade's `trace_id`**:
   - BUY correct if price moved up by more than `EVAL_SIGNIFICANCE_PCT` (1 %).
   - SELL correct if price moved down by more than 1 %.
   - Otherwise `was_correct` stays `NULL` (inconclusive) but the pending row is marked `evaluated=1` to avoid retry loops.
3. `_compute_dynamic_weights` only blends accuracy when an agent has ≥ 5 evaluated votes (`_MIN_EVALUATED_VOTES`). Until then it returns the static `WEIGHTS` dict — the frontend surfaces this as `⏳ Calibrating` / `✓ Market-validated` badges.

All SQLite writes go through `_db_write()` / `_db_write_multi()` in `agents/shared/db.py` (retries, `with closing(...)`, logging on failure). All reads go through `_db_read()` in the same module: it uses `_get_db_path()` for sim vs live, triggers `_ensure_db()`, sets `PRAGMA busy_timeout=5000` per connection, and retries on lock contention — used via `agents.shared.nodes` re-exports by agent nodes and by `api/routes/portfolio.py` (trades, agent memory, postmortem rows serialized for `/api/trades` / `/api/analytics`).

### LiveFeed

`LiveFeed` in `core/data.py` provides multi-symbol price fetching using 1m yfinance history. Wired into `Portfolio.fetch_prices()` when `USE_LIVEFEED=True`. Falls back to `yf.Tickers` fast_info silently on error.

### Terminal tab (`frontend/src/components/terminal/TerminalTab.tsx`)

Beyond the macro bar, watchlist cards, chart, news, and screener, the TERMINAL tab renders:

| Block | Hook / route | Role |
|-------|--------------|------|
| **Sector rotation** | `useSectors()` → `GET /api/market/sectors` | `fetch_sector_performance()` heatmap (% vs period presets) |
| **Correlation matrix** | `useCorrelation()` → `GET /api/market/correlation` | `fetch_correlation_matrix()` (Pearson on daily returns); needs ≥ 2 symbols |

**Enriched macro bar** (`useMacro()` → `GET /api/market/macro`): VIX / SPY / DXY blocs; adds **CNN Fear & Greed** (`fetch_fear_greed` via `core/external_data.py`), **FED funds** and **10Y** from FRED (`fetch_fred_latest`), each with the same refresh cadence as the rest of the bar.

Note: `market_data/economic_calendar.py` (`build_economic_calendar_rows()`) is exercised by tests but is not yet surfaced by an `api/routes/` endpoint or frontend component.

### Discord alerts beyond trades

When `DISCORD_WEBHOOK_URL` is set, `core/notifications.py` also supports:

| Function | When |
|----------|------|
| `alert_daily_digest` | End-of-day portfolio summary — scheduled from `run_daily_digest()` (`runtime/controller.py` postmortem thread) |
| `alert_weekly_report` | Weekly agent ranking / stats — `run_weekly_report()` |
| `alert_evaluation` | After `evaluate_pending_trades` resolves `was_correct` for a trade (`agents/shared/eval.py`) |

All use the same fail-silent `httpx.post` pattern as trade alerts.

## Configuration

All tuneable constants are in `config.py`. Env vars override at startup:

| Env var | Default | Effect |
|---------|---------|--------|
| `ANTHROPIC_API_KEY` | — | Required for live mode |
| `SIMULATION_MODE` | `false` | Random-walk prices + rule-based decisions + `trades_sim.db` |
| `PAPER_MODE` | `false` | Real prices + rule-based decisions + `trades_paper.db` (mutually exclusive with `SIMULATION_MODE`) |
| `SIM_VOLATILITY` | `0.02` | Price random-walk std dev per step |
| `SIM_DRIFT` | `0.0001` | Price drift per step |
| `EVAL_HORIZON_DAYS` | `5` | Trading-day target for ``was_correct`` evaluation |
| `EVAL_HORIZON_CALENDAR_DAYS` | `7` | Calendar-day approximation used to schedule ``pending_evaluations.eval_after_date`` |
| `X_BEARER_TOKEN` | — | Twitter/X sentiment (optional) |
| `USE_LIVEFEED` | `true` | Delegate Portfolio.fetch_prices() to LiveFeed; set `false` in tests |
| `PORTFOLIO_STATE_PATH` | `portfolio_state.json` | Path for JSON portfolio persistence |
| `PORTFOLIO_SAVE_ENABLED` | `true` | Enable/disable Portfolio save_state(); set `false` in unit tests |
| `DISCORD_WEBHOOK_URL` | — | Optional Discord webhook for `core.notifications` (trades, death, stagnation, rate-limit, startup, **daily digest**, **weekly report**, **evaluation**) |
| `FRED_API_KEY` | — | Optional; FRED JSON works for many series without a key but is **rate-limited** — key improves limits |
| `MACRO_SYMBOLS` | `{"VIX": "^VIX", "SPY": "SPY", "DXY": "DX-Y.NYB"}` | Symbols for the TERMINAL macro header bar |
| `MARKET_DATA_CACHE_SEC` | `60` | TTL for macro data cache (`market_data.caches` / `macro.py`) |
| `WATCHLIST_CACHE_SEC` | `10` | TTL for watchlist prices cache (`market_data.caches` / `quotes.py`) |
| `NEWS_MAX_ITEMS` | `8` | Max news items returned by `fetch_news()` |
| `MAX_PYRAMID_LAYERS` | `3` | Env `MAX_PYRAMID_LAYERS` — max BUY layers per symbol (`Portfolio.buy` pyramiding; weighted `avg_price`) |
| `DASHBOARD_PASSWORD` | — | Optional; when set, requires a matching Bearer token on REST routes and `?token=` on `/ws` (`/health` stays open for monitoring). Unset = no auth (localhost default) |

`WATCHLIST`, `INITIAL_BALANCE`, `DEATH_THRESHOLD`, `MAX_POSITIONS`, `MAX_ALLOC_PCT`, `AGENT_INTERVAL`, `STOP_LOSS_PCT`, `POSTMORTEM_HOUR`, and the trade-lifecycle guards (`TAKE_PROFIT_PCT` 10%, `TAKE_PROFIT_SELL_PCT` 50, `TIME_STOP_DAYS` 10, `TIME_STOP_BAND_PCT` 2%, `MAX_DRAWDOWN_BLOCK_PCT` 20%, `EARNINGS_BLOCK_DAYS` 2) are hardcoded in `config.py` and not overridable by env vars.

## Known pitfalls

- **FRED API** — works without `FRED_API_KEY` for many popular JSON series, but responses are **rate-limited**. Set `FRED_API_KEY` in `.env` for higher quotas and more predictable access (`core/external_data.fetch_fred_latest`).
- **Fear & Greed** — CNN `production.dataviz.cnn.io` endpoint is **undocumented** and may change without notice. `fetch_fear_greed` is **fail-silent** (bar shows `F&G: —` on failure).
- **Earnings calendar** — `yf.Ticker.calendar` shape varies across **yfinance** versions (dict vs DataFrame, column names). `market_data.fetch_earnings_calendar` and `build_economic_calendar_rows` must stay wrapped in **try/except**; never assume a single format.
- **`_SCHEDULED_MACRO_EVENTS`** — calendrier macro **fallback** dans `market_data/economic_calendar.py`. CPI/NFP sont désormais récupérés via FRED (`fetch_fred_release_dates`, ids 10/50) par `_get_macro_events()` ; le **FOMC** (pas un *release* FRED) et le mode **hors-ligne** retombent sur cette liste statique — **toujours à mettre à jour trimestriellement**. `logger.warning` se déclenche si la date du jour dépasse la dernière date de la liste.
- **`market_data/fundamentals.py`** — `fetch_fundamentals(symbol)` via `yf.Ticker(...).info`, **cache 1 h** (lourd + rate-limité, ne jamais appeler par tick). Fail-silent : sert le cache stale ou `{}` en cas d'échec. Surfacé sous le chart du terminal (`_fundamentals_strip`).
- **`walk_forward_backtest`** — `core/backtest.py` découpe l'historique en N folds disjoints et rejoue `_simulate` (extrait de `run_backtest`, logique d'exécution partagée) sur chacun depuis le cash initial → rendement moyen / % de folds gagnants / consistance. Surfacé dans l'onglet backtest.
- **Reads cross-mode** — `_db_read_at(path, query)` + `mode_db_path(mode)` (`agents/shared/db.py`, réexportés via `agents.shared.nodes`) lisent un fichier DB **explicite** (`trades.db` / `trades_paper.db`) sans passer par `_get_db_path()` et **sans créer** le fichier (retourne `[]` s'il manque) — utilisés par le panneau LIVE vs PAPER de l'onglet analytics.
- **`fetch_earnings_calendar`** — réponses **mises en cache 5 min** (`_EARNINGS_TTL`, clé = ensemble de symboles trié). Ne pas l’appeler directement depuis une route API **à chaque requête** sans passer par ce cache (surcharge yfinance).
- **Pyramiding** — `MAX_PYRAMID_LAYERS` (default 3, env `MAX_PYRAMID_LAYERS`) caps successive BUYs on the same symbol; `avg_price` is recomputed as a **share-weighted** average. Past the cap, `buy()` returns `{"success": False, "error": "max pyramid layers (…) reached"}` — `execute_node` checks `result["success"]`. **`high_watermarks`** for trailing stop is set on the **first** open only — pyramids do **not** reset it.
- **Trade lifecycle guards in `execute_node`** — beyond the trailing stop: partial **take-profit** (sells `TAKE_PROFIT_SELL_PCT`% once at +`TAKE_PROFIT_PCT` vs `avg_price`; the per-position `tp_taken` flag prevents re-firing), **time-stop** (full exit when held > `TIME_STOP_DAYS` calendar days with PnL within ±`TIME_STOP_BAND_PCT`; needs `opened_at`, set on first open — legacy positions without it are skipped), and a **drawdown guard** (BUY converted to no-op when drawdown from `peak_value` ≥ `MAX_DRAWDOWN_BLOCK_PCT`).
- **Earnings hard block** — `risk_check_node` **fails** a BUY when earnings are within `EARNINGS_BLOCK_DAYS` (2) days (uses `state["earnings_calendar"]`, already fetched per cycle); 3–5 days out still only damps allocation (×0.65 via `is_earnings_week`). A **volatility guard** in the same node damps allocation (×0.75 above 2% daily vol, ×0.5 above 3%) using the same close series as RSI.
- **`core/metrics.py`** — canonical Sharpe/Sortino/max-drawdown/Kelly/volatility implementations (pure functions, no I/O). `core/backtest.py` and `_compute_risk_metrics` in `agents/shared/nodes.py` (state key `risk_metrics`, consumed by `risk_manager_node`) both use it — do not re-implement these metrics elsewhere. `risk_manager_node` computes Kelly from **real** `postmortem.pnl_pct` rows once ≥ 5 closed trades exist (conservative priors before that).
- **`pending_evaluations.retry_count`** — incremented when `_fast_last_price` returns `None`; the row is abandoned (`evaluated=1` + warning) after 10 consecutive failures (`_MAX_EVAL_RETRIES` in `agents/shared/eval.py`). Soft-migrated like the other columns.
- **Watchlist DB** — at most **20** symbols (`agents.shared.watchlist.MAX_WATCHLIST_SYMBOLS`). **`remove_from_watchlist`** refuses to drop a ticker that still has an **open position** (`open_symbols`).
- **`core/` dependency rule** — **`core/` must NEVER import from `agents/` or `runtime/`**. Pass runtime data (e.g. watchlist symbols, `get_runtime_mode()`) as **parameters** from callers in `agents/` or `runtime/`.
- **Discord webhook alerts** — `core.notifications` uses fire-and-forget `httpx.post` (5s timeout). Fail-silent on errors; never blocks the agent loop. Wire points use lazy imports (`core.data` ↔ `agents.shared.nodes`). Leave `DISCORD_WEBHOOK_URL` unset to disable.
- **CI jobs** — `.github/workflows/ci.yml`: job `lint` runs `uv run black --check .` only; job `test` runs ruff + pytest + coverage; job `security` runs `ruff check . --select S` (flake8-bandit); job `frontend` runs `tsc --noEmit` + `npm test` + `npm run build` in `frontend/`. Failing `lint` on push: reproduce with `uv run black --check --diff .`.
- **`README.md`** — root `README.md` is a symlink to `docs/README.md`; commit `docs/README.md` when updating user-facing README.
- **`_init_db()` test DB path** — if `_get_db_path()` is not the repo `trades.db` / `trades_sim.db` (e.g. `tmp_db` monkeypatch on `agents.shared.db._get_db_path`), `_init_db()` initializes only that file — avoids writing project DBs during tests.
- **GitHub MCP** — typically no Actions run logs; debug CI with the same `uv run` commands locally.
- **yfinance MultiIndex** — depuis yfinance 0.2.38+, `yf.download()` peut retourner un DataFrame en colonnes MultiIndex. Toujours passer `auto_adjust=True` ou aplatir avec `df.columns = df.columns.get_level_values(0)` avant d’accéder à `df["Close"]` (voir `_seed_live_price_history`).
- **`_seed_live_price_history` bloque `fetch_data_node`** — au premier cycle live, le téléchargement ~1 mois par symbole prend ~2–5 s chacun. Le seed est protégé par `_live_price_history_lock` pour éviter un double seed en fan-out (multi-agent).
- **`HOLD` trades not saved** — `save_memory_node` returns early on HOLD. Patterns table only contains BUY/SELL lessons.
- **`avg_price` vs `avg_cost`** — both keys appear in `_portfolio_value()` due to backward compat (`pos.get("avg_price", pos.get("avg_cost", 0))`). New positions always use `avg_price`.
- **`trades.db` soft migration** — on startup, `agents/shared/db.py` tries `ALTER TABLE trades ADD COLUMN source …` and `ADD COLUMN trace_id …`, and silently catches `OperationalError` if columns exist. Do not remove these blocks.
- **`research` goes directly to `risk_check`** — `research_node` does not loop back to `arbitrate`. This is intentional.
- **`LiveFeed` not wired into graph nodes** — `LiveFeed` is wired into `Portfolio.fetch_prices()` only; it is not a LangGraph node.
- **`agents/registry.py` description** — keep `GRAPH_INFO` in sync with the specialist set in `agents/multi.py` (`WEIGHTS` keys). The registry lives in `agents/` (moved from `core/`) because it imports `agents.multi` and `core/` must never depend on `agents/`.
- **Postmortem thread started from `runtime/controller.py`** — `run_daily_postmortem()` is never called from `main.py` directly; `start_controller()` (which spawns the postmortem thread) runs from `api/main.py`'s `lifespan` hook on real ASGI startup, so it only fires when the FastAPI app actually serves (e.g. via `uvicorn`/`main.py`), not on a bare `import api.main`.
- **`market_data` caches** — macro 60s, watchlist 10s (`market_data.caches`) pour limiter yfinance. Cache mémoire uniquement ; reset au redémarrage. Un **circuit breaker yfinance** (`yf_circuit_open` / `record_yf_failure` / `record_yf_success` dans `caches.py`) s'ouvre après 3 échecs consécutifs et sert le cache stale pendant 60 s — câblé dans `quotes.py` et `macro.py`.
- **Sentiment Twitter neutre sans token** — `_fetch_sentiment_sync` retourne `0.0` par symbole quand `X_BEARER_TOKEN` est absent (plus de bruit aléatoire ±0.3 traité comme signal).
- **`market_data` découpé** — package sans import `agents/` ou `runtime/` (règle inchangée).
- **`USE_LIVEFEED=False` in tests** — set via env or config override to avoid yfinance rate limiting during test runs.
- **`portfolio_state.json` created on first run** — added to `.gitignore`, do not commit.
- **`PORTFOLIO_SAVE_ENABLED=True` by default** — set to `False` in unit tests to avoid disk writes.
- **`agents/` → `runtime/`/`api/` import direction is forbidden** — `agents/shared/nodes.py` imports from `core.data`. Never import from `runtime` or `api` in any `agents/` file. This violates the one-way dependency rule (`api`/`runtime` depend on `agents`/`core`, not the reverse).
- **Lazy DB init** — `_init_db()` is no longer called at import time. It runs lazily on first `_db_write`/`_db_read`/`_db_write_multi` call via `_ensure_db()`. Importing `agents/shared/nodes.py` no longer creates SQLite tables. Importing `runtime/controller.py` does not create a `Portfolio` until `start_controller()` is called explicitly. Importing `agents/multi.py` compiles the LangGraph graph at module level (for LangGraph Studio compatibility). Initialization state is tracked **per resolved DB path** (`_db_initialized_paths` set) so initializing one path never marks another (e.g. a test tmp DB) as done.
- **RSI/MACD/Bollinger in `core/indicators.py`** — canonical `rsi()`, `ema()`, `macd()`, `bollinger_bands()`, `bb_position()`. Do not re-implement them elsewhere. The scalar `macd()`/`bollinger_bands()` use the same `ewm(adjust=False)` + sample-std (ddof=1) conventions as `core/backtest.py compute_indicators`, so the latest values match across the technician, terminal watchlist (`macd_hist`/`bb_pos` in `fetch_watchlist_prices`), and backtest — verified by `tests/test_indicators.py`.
- **`_db_write()` / `_db_read()` centralize all SQLite access** — never open raw `sqlite3.connect()` anywhere — not in agent nodes, not in `api/routes/`. Always use `_db_write()` or `_db_read()` from `agents.shared.nodes` (implementations in `agents.shared.db`; `api/routes/portfolio.py` uses `_db_read()` directly so REST/WS analytics match the active sim/paper/live mode).
- **\_live\_price\_history warm-up** — en live mode, le RSI retourne 50.0 (`insufficient data`) pendant les 14 premiers cycles (~7 min) si la série n’est pas encore prête. Le technician est aveugle pendant cette période (mitigation : seed daily + append par jour, sprint v3).
- **Live mode `technician_node` RSI** — Live closes are appended in `fetch_data_node` (live path) to `_live_price_history` in `agents/shared/nodes.py` (last 100 per symbol). The multi-agent `technician_node` uses that series for RSI; simulation still uses `_sim_price_history` from `_sim_step_prices()`.
- **`_route_risk` fail-closed** — `_route_risk` defaults `_risk_passed` to `False` (fail-closed). If `risk_check_node` fails to write `_risk_passed`, the graph skips execution instead of proceeding.
- **`/health` and agent liveness** — `api/main.py` returns HTTP **503** when `portfolio.is_dead` (or no portfolio), **200** when alive; JSON includes `status` (`ok` / `dead`) and `agent_alive`.
- **Zero-price stop-loss** — `execute_node` runs SL only when `sl_avg > 0`, `sl_price > 0`, and the quote is plausible: `sl_price > 1.0`, or both cost basis and quote are ≤ $1 (penny stocks). Otherwise it skips SL and logs a warning (`Skipping stop-loss check…`) — avoids bogus ticks (e.g. yfinance 0 / stale sub-dollar quote vs a normal-cost basis) without spamming every cycle on legitimate sub-dollar names.
- **Backtest vs live RSI** — `core/backtest.py` `compute_indicators()` uses `core.indicators.rsi()` for `RSI_14` (same function as agents). Do not reintroduce pandas EWM for RSI.
- **`test_sqlite_schema` runs against a temp DB** — `tests/test_smoke.py` redirects `_get_db_path` to a temp file (mirroring the `tmp_db` fixture, but fixture-free so the legacy runner works), calls `_ensure_db()` there, and never writes the project `trades.db`.
- **Token budget resets daily** — `_maybe_reset_token_counter()` in `agents/shared/llm.py` is called at the start of each `_llm()` invocation and resets `_token_counter` at midnight. **`_maybe_reset_token_counter()` acquiert `_token_counter_lock` lui-même** — ne jamais l’appeler depuis une section déjà verrouillée par `_token_counter_lock`, sinon deadlock.
- **All LLM specialist votes validated by Pydantic** — `technician_node`, `analyst_node`, `risk_manager_node`, `macro_watcher_node`, `economist_node`, `geopolitician_node` and `arbitrate_node` all pass raw LLM JSON through their respective `validate_*_vote()` / `validate_decision()` functions from `agents/shared/schemas.py`.
- **`was_correct` is deferred** — `agent_memory.was_correct` reflects the actual market move 5 trading days after the trade (resolved by `evaluate_pending_trades`), not the arbitration consensus. Right after a trade, `was_correct IS NULL`; the frontend shows `⏳ Calibrating` per agent until ≥ 5 evaluated votes accumulate.
- **Paper mode reuses sim decision nodes** — `_no_llm_mode()` is `True` in both sim and paper, so any change to `sim_technician`, `sim_analyst`, `sim_risk_manager`, `sim_macro_watcher`, the `_no_llm_mode()` branch in `arbitrate_node`, or the `[SIM]/[PAPER]` lesson tag in `save_memory_node` directly affects paper trading. Only `fetch_data_node` diverges (paper uses the live yfinance branch).
- **Mode switch is mutually exclusive** — `set_paper_mode(True)` clears `_sim_mode`, and `set_simulation_mode(True)` clears `_paper_mode`. Never set both flags directly via `_paper_mode["enabled"] = True`; always go through the setters so `.env` stays in sync.
- **`pending_evaluations` retry policy** — rows are flagged `evaluated=1` even when the verdict is inconclusive (move below `EVAL_SIGNIFICANCE_PCT`) to prevent infinite retries. The only path back to `evaluated=0` is when `_fast_last_price` returns `None` (network/quote unavailable) — those rows are retried at the next tick.
- **Dynamic weights graceful warm-up** — `_compute_dynamic_weights` returns the static `WEIGHTS` dict verbatim while no agent has ≥ `_MIN_EVALUATED_VOTES` (5) evaluated votes. Holding `_weights_lock` (threading.Lock) during cache check + DB read prevents thundering-herd recomputation.
- **Postmortem thread also runs `evaluate_pending_trades`** — every 60 s tick, regardless of `POSTMORTEM_HOUR`. Skipped under SIM mode (random-walk prices would corrupt `was_correct`); runs under LIVE and PAPER.
- **Raw `sqlite3.connect` forbidden outside `agents/shared/db.py`** — `api/routes/portfolio.py` uses `_db_read()` so REST responses follow the active DB path (sim/paper/live). Do not reintroduce `sqlite3.connect(DB_PATH)` elsewhere.
- **`agent_memory.trace_id` invariant** — must exist in `_SCHEMA` AND be written by `_record_vote`. If either is missing, `evaluate_pending_trades` silently fails (UPDATE matches zero rows) and `was_correct` stays NULL forever. The regression guard is `tests/test_smoke.py::test_agent_memory_has_trace_id`.
- **API auth gate** — `api/auth.py`'s `require_auth` (a FastAPI `Depends`) gates REST routes with a Bearer-token check (`Authorization: Bearer <DASHBOARD_PASSWORD>`); `ws_auth_ok` validates the `/ws` handshake via a `?token=` query param instead, since browser WebSockets can't set custom headers. Both are no-ops when `DASHBOARD_PASSWORD` is unset (`_auth_enabled()` reads `config.DASHBOARD_PASSWORD` at **request time**; tests monkeypatch it). `/health` is always exempt. The `/ws` Origin allow-list (`ALLOWED_ORIGINS`, the Vite dev server) is enforced **unconditionally**, even with no password set, to prevent Cross-Site WebSocket Hijacking. There is no session/cookie state.

## Code conventions

- Frontend styling in `frontend/src/styles/globals.css` (design tokens as CSS custom properties) — reuse them everywhere, don't hardcode colors in components
- Emotion system: `_derive_emotion(value)` in `api/serializers.py` derives state from portfolio value ratio for the `/api/portfolio` payload and WS snapshots
- All LLM outputs validated through Pydantic models in `agents/shared/schemas.py`
- Structured logging via `logging.getLogger("apex7")` — do not use bare `print()` for operational logs
