# APEX-7 // SURVIVAL TRADER

[![CI](https://github.com/Brescou/apex7-trader/actions/workflows/ci.yml/badge.svg)](https://github.com/Brescou/apex7-trader/actions/workflows/ci.yml)

> An autonomous AI trading agent built on LangGraph + Claude, with a real-time Bloomberg-style terminal dashboard.
> The agent starts with $1,000 and must survive — it dies if its portfolio falls below $50.

---

## Table of contents

1. [Concept](#concept)
2. [Architecture overview](#architecture-overview)
3. [Technical choices — why & how](#technical-choices--why--how)
4. [Project structure](#project-structure)
5. [Installation](#installation)
6. [Configuration](#configuration)
7. [Running the project](#running-the-project)
8. [Frontend guide](#frontend-guide)
9. [Simulation vs Live mode](#simulation-vs-live-mode)
10. [LangGraph Studio](#langgraph-studio)
11. [Extending the project](#extending-the-project)

---

## Concept

APEX-7 is a **survival trading agent**: it operates under existential pressure with a hard death floor at $50. This constraint forces the agent to reason about risk explicitly rather than optimize a simple return metric.

Every cycle the agent:
1. Loads its trade memory from SQLite
2. Fetches real market data (prices, news, social sentiment)
3. Analyzes the market with Claude Sonnet (with optional web search)
4. Optionally performs deep research (if confidence < 70%)
5. Validates its decision against risk rules
6. Executes the trade and saves a lesson to memory

The entire reasoning process is visible in real time on the terminal dashboard.

---

## Architecture overview

### Runtime topology

```
┌─────────────────────────────────────────────────────────────┐
│         frontend/ (React 18 + Vite + TypeScript)              │
│  Live · Terminal · Analytics tabs                             │
│  REST polling + WebSocket (/ws) → portfolio state display     │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST + WS
┌──────────────────────────▼──────────────────────────────────┐
│              api/ (FastAPI: main.py, routes/, ws)             │
│  auth.py (Bearer token), broadcaster.py (WS push, 500ms)      │
└──────────────────────────┬──────────────────────────────────┘
                           │ reads
┌──────────────────────────▼──────────────────────────────────┐
│                   Portfolio (core/data.py)                    │
│  Thread-safe state: cash, positions, value_history, logs     │
└──────────────────────────┬──────────────────────────────────┘
                           │ managed by
┌──────────────────────────▼──────────────────────────────────┐
│            Agent loop (dashboard/controller.py)              │
│  pause / step / reset controls via shared _ctrl dict          │
│  started from api/main.py's FastAPI lifespan hook              │
└──────────────────────────┬──────────────────────────────────┘
                           │ invokes
┌──────────────────────────▼──────────────────────────────────┐
│        LangGraph compiled graph (agents/multi.py)            │
└─────────────────────────────────────────────────────────────┘
```

There is a **single** compiled graph (`agents/multi.py:agent_multi_graph`),
exposed to LangGraph Studio via `langgraph.json`. The legacy single-agent
graph and the `AGENT_GRAPH` env toggle have been removed.

### Multi-agent graph

```
  __start__
      │
  load_memory ← SQLite
      │
  fetch_data  ← yfinance + news + sentiment
      │
  supervisor  ← Haiku (context brief for team)
      │
      ├─────────────────────────────────────┐
      │ Send() parallel fan-out             │
      ▼                                     ▼
  ┌────────────┐  ┌──────────┐  ┌───────────────┐  ┌──────────────┐
  │ technician │  │ analyst  │  │ risk_manager  │  │ macro_watcher│
  │ (Haiku)    │  │ (Sonnet) │  │ (Haiku)       │  │ (Haiku)      │
  │ RSI/MACD   │  │ news+web │  │ VaR/Kelly     │  │ regime/bias  │
  └─────┬──────┘  └────┬─────┘  └──────┬────────┘  └──────┬───────┘
        │              │               │                   │
        └──────────────┴───────────────┴───────────────────┘
                               │
                         arbitrate ← Sonnet (weighted vote fusion)
                               │
                         conf ≥ 0.72? ──► risk_check
                               │              │
                           research       pass ──► execute ──► save_memory
                                          fail ──► skip
```

All specialist votes are validated through **Pydantic models** (`TechVote`, `AnalystVote`, `RiskVote`, `MacroVote`) before arbitration.

### Persistence

```
┌────────────────────────────────────────────────────────────┐
│  trades.db (live) / trades_paper.db (paper) /              │
│  trades_sim.db (simulation)                                │
│  tables: trades, patterns, agent_memory, postmortem,       │
│          pending_evaluations, watchlist                    │
│  (trades: trace_id, prompt_version, source)                │
│  WAL mode + busy_timeout=5000ms                            │
│  All access via _db_write() / _db_read()                   │
└────────────────────────────────────────────────────────────┘
```

---

## Technical choices — why & how

### LangGraph as the agent framework

LangGraph was chosen over a plain prompt loop for three reasons:

- **Explicit graph structure** — each node is a pure function with a typed `AgentState`. The flow is readable, testable, and easy to extend (add a node, wire an edge).
- **Conditional routing** — the `analyze → research → analyze` loop and the `risk_check → execute|skip` branch are expressed as graph edges, not buried in if/else logic.
- **State accumulation** — `Annotated[List, operator.add]` on `log` and `portfolio_history` fields lets nodes append without overwriting, removing the need for manual state merging.

The compiled graph is also exposed to **LangGraph Studio** via `langgraph.json` for visual debugging.

### Two-model strategy (Sonnet + Haiku)

| Task | Model | Why |
|------|-------|-----|
| Market analysis, research, arbitration | `claude-sonnet-4-5` | Complex reasoning, web search, JSON output |
| Memory extraction, supervisor brief | `claude-haiku-4-5-20251001` | Fast, cheap — runs on every cycle |
| Technician, risk manager, macro watcher | `claude-haiku-4-5-20251001` | Structured output, latency-sensitive |

This keeps the expensive model where reasoning quality matters and the cheap model for boilerplate LLM work.

**API safety**: a circuit breaker pauses calls after repeated failures (including opening immediately on HTTP 429 with `Retry-After`; 5 min cooldown after generic failures). A daily token budget cap (500K tokens) prevents runaway costs. The counter resets at midnight.

### Web search as a native tool

Claude's `web_search_20250305` tool is used directly via the Anthropic SDK in an agentic loop — not as a LangChain wrapper. The `_llm()` helper handles the tool-use cycle (up to 8 iterations) and returns the final assistant text. This gives the agent real-time market intel without maintaining a separate search API integration.

### Pydantic validation for LLM outputs

All LLM JSON outputs pass through Pydantic models in `agents/shared/schemas.py`:

| Model | Used by | Key validations |
|-------|---------|-----------------|
| `DecisionOutput` | `analyze_node`, `arbitrate_node` | action, confidence, allocation_pct, emotion |
| `TechVote` | `technician_node` | action, confidence, key_indicators (RSI/MACD/BB) |
| `AnalystVote` | `analyst_node` | catalysts, sentiment_score |
| `RiskVote` | `risk_manager_node` | risk_score [0-10], sizing_recommendation, VaR |
| `MacroVote` | `macro_watcher_node` | market_regime, macro_bias, macro_score |

Invalid values are clamped (confidence > 1.0 → divided by 100, allocation > 100% → capped). If the entire model fails validation, safe defaults are returned (HOLD, 0.5 confidence).

### Simulation mode

A full simulation engine runs with zero network calls:
- Prices follow a configurable random-walk (`SIM_DRIFT`, `SIM_VOLATILITY`)
- RSI is computed from the simulated price history (canonical implementation in `core/indicators.py`)
- Decisions are rule-based (oversold → BUY, overbought → SELL, else HOLD)
- No LLM is called in simulation mode
- Trades are stored in a separate `trades_sim.db` to avoid contaminating live data

This makes it possible to test the full agent loop, dashboard, and trade logic instantly and for free. Switching between modes is live — no restart required.

### Portfolio as shared state (not agent state)

The `Portfolio` object lives in the main process and is accessed by both the agent thread and the FastAPI request/WebSocket-broadcaster thread. All mutations are protected by `threading.RLock()`. The agent's `AgentState` (the LangGraph state dict) is a snapshot passed per-cycle; the portfolio is the source of truth for the API.

This separation means:
- The API can read portfolio state at any time without blocking the agent
- The agent can be paused, stepped, or reset without touching the graph internals

### SQLite for memory

SQLite was chosen over a vector database because:
- The trade history is small and structured (rows, not embeddings)
- SQL filters and sorts (last 20 trades, patterns by timestamp) are exactly what's needed
- Zero infrastructure — the file lives next to the code, auto-created on first access

All writes go through `_db_write()` / `_db_write_multi()` (retries, context managers, logging). All reads through `_db_read()`. Both use `_get_db_path()` to route to the correct sim/live database. WAL mode and `busy_timeout=5000ms` handle concurrent access from the agent, postmortem, and dashboard threads.

### FastAPI + React for the terminal UI

The original all-Python Dash dashboard was replaced by a FastAPI backend (`api/`) and a React 18 + Vite + TypeScript frontend (`frontend/`), giving a real WebSocket push channel and a conventional frontend toolchain (component tests, type checking, a real build step) instead of server-rendered callbacks.

Key patterns used:
- `api/broadcaster.py` polls the shared portfolio state every 500ms and pushes JSON snapshots + agent-vote diffs over a single `/ws` WebSocket connection
- `frontend/src/hooks/useWebSocket.ts` consumes the live stream; `frontend/src/hooks/useApex.ts` handles REST polling for slower-moving data (watchlist 10s, macro/sectors 60s, correlation 120s)
- `api/auth.py` gates REST routes behind a Bearer token and the `/ws` handshake behind a `?token=` query param, both only when `DASHBOARD_PASSWORD` is set
- `api/main.py`'s `lifespan` hook starts the agent loop (`dashboard/controller.start_controller()`) only on real ASGI startup — importing the module has no side effects

---

## Project structure

```
apex7-trader/
├── main.py                         # Entrypoint: runs api.main:app via uvicorn (port 8000)
├── config.py                       # All constants, loaded from .env
├── market_data/                    # Package market data (macro, quotes, terminal…)
├── langgraph.json                  # LangGraph Studio config
├── pyproject.toml                  # Dependencies (uv) + black/ruff/pytest config
├── Dockerfile                      # Multi-stage image (uv, python 3.12, port 8000)
├── .dockerignore
├── CLAUDE.md                       # Maintainer / agent context (detailed pitfalls)
│
├── agents/                         # Agent graph and shared logic
│   ├── multi.py                    # Multi-agent graph (4 specialists + arbitration)
│   ├── registry.py                 # Single graph builder + UI metadata
│   └── shared/
│       ├── state.py                # AgentState, MultiAgentState TypedDicts
│       ├── nodes.py                # Shared nodes, DB helpers, sim engine, _llm()
│       ├── eval.py                 # Deferred was_correct evaluation
│       ├── prompts.py              # Versioned system prompts (PROMPT_VERSION)
│       └── schemas.py              # Pydantic validation for all LLM outputs
│
├── core/                           # Domain logic (no UI, no agents)
│   ├── data.py                     # Portfolio (thread-safe), LiveFeed
│   ├── backtest.py                 # run_backtest(), compare_strategies()
│   ├── indicators.py               # Canonical RSI implementation
│   └── metrics.py                  # Sharpe/Sortino/drawdown/Kelly (pure functions)
│
├── dashboard/                      # Agent-loop / Portfolio-state machinery
│   ├── __init__.py                 # Package docstring only (no UI code here anymore)
│   └── controller.py               # Agent loop, portfolio state, postmortem thread
│
├── api/                            # FastAPI backend
│   ├── main.py                     # FastAPI() app, lifespan hook (start_controller), /health
│   ├── auth.py                     # Bearer-token auth gate (DASHBOARD_PASSWORD)
│   ├── broadcaster.py              # WebSocket broadcaster (polls portfolio state, 500ms)
│   ├── serializers.py              # Portfolio/trade/vote → JSON dicts
│   └── routes/
│       ├── portfolio.py            # /api/portfolio, /api/trades, /api/analytics
│       ├── market.py               # /api/market/* (macro, watchlist, sectors, news, …)
│       ├── control.py              # /api/control/* (mode, pause/resume, watchlist CRUD)
│       └── ws.py                   # /ws WebSocket endpoint
│
├── frontend/                       # React 18 + Vite + TypeScript terminal UI
│   ├── package.json
│   └── src/
│       ├── App.tsx
│       ├── components/{live,terminal,analytics,layout}/
│       ├── hooks/                  # useWebSocket.ts, useApex.ts
│       └── types/
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CHANGELOG.md
│   └── README.md                   # Docs index / extras
│
├── tests/                          # pytest tests (see CI)
│   ├── conftest.py                 # sim_mode, portfolio, tmp_db (isolated SQLite)
│   ├── test_smoke.py               # Import/graph/backtest/smoke (legacy runner still supported)
│   ├── test_api.py                 # FastAPI app + lifespan (TestClient), auth
│   ├── test_integration.py         # Graph flows, schemas, DB helpers, token reset
│   ├── test_terminal.py            # market_data (macro, watchlist, news, screener…)
│   ├── test_layout_helpers.py      # agents/registry.py graph builder
│   ├── test_circuit_breaker.py     # LLM circuit breaker + rate-limit behavior
│   ├── test_stoploss.py            # execute_node stop-loss guards
│   ├── test_portfolio.py           # Portfolio.sell() validation
│   ├── test_metrics.py             # core.metrics pure functions
│   ├── test_misc_coverage.py       # RSI seed mocks, misc paths
│   └── ...                         # one file per subsystem — see tests/ for the full list
│
├── .github/workflows/ci.yml        # CI: jobs test (ruff+pytest+coverage), lint (black),
│                                    #     security (ruff flake8-bandit), frontend (tsc+vitest+build)
├── .pre-commit-config.yaml          # ruff + black + standard hooks
├── .env                             # API keys (not committed)
├── trades.db                        # Live SQLite (auto-created, not committed)
└── trades_sim.db                    # Sim SQLite (auto-created, not committed)
```

---

## Installation

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
# Clone the repository
git clone git@github.com:Brescou/apex7-trader.git
cd apex7-trader

# Install dependencies
uv sync
```

---

## Configuration

Create a `.env` file at the project root:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional — Twitter/X sentiment analysis
X_BEARER_TOKEN=...

# Optional — agent behavior
SIMULATION_MODE=true        # random-walk prices + rule-based decisions (no LLM)
PAPER_MODE=false            # real prices + rule-based decisions (no LLM)
SIM_VOLATILITY=0.02         # price volatility per step (default 2%)
SIM_DRIFT=0.0001            # slight upward drift (default 0.01%)
```

**Watchlist, balance, and thresholds** are configured directly in `config.py`:

```python
WATCHLIST       = ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA"]
INITIAL_BALANCE = 1000      # starting cash ($)
DEATH_THRESHOLD = 50        # portfolio floor ($) — agent dies below this
MAX_POSITIONS   = 3         # maximum simultaneous open positions
MAX_ALLOC_PCT   = 40        # max % of portfolio per trade
AGENT_INTERVAL  = 30        # seconds between live cycles
STOP_LOSS_PCT   = 0.05      # stop-loss threshold (5%) — enforced before agent decision
POSTMORTEM_HOUR = 22        # hour (0-23) at which daily postmortem runs
```

---

## Running the project

```bash
# Start the FastAPI backend + agent
uv run python main.py

# For local frontend development with hot reload, in a second terminal:
cd frontend && npm install && npm run dev

# Run all tests (full suite; coverage optional — matches CI job "test")
uv run pytest tests/ -v --tb=short

# Run smoke tests only (legacy runner)
uv run python tests/test_smoke.py

# Lint
uv run ruff check . --select E,F,W --ignore E501

# Format check
uv run black --check .

# Optional: container (see Dockerfile)
# docker build -t apex7:latest .
# docker run --rm -e ANTHROPIC_API_KEY=... -p 8000:8000 apex7:latest
```

Open **http://localhost:8000** in your browser (or the Vite dev server URL, typically `http://localhost:5173`, when running the frontend separately for hot reload — it proxies API/WS calls to `:8000`).

The agent starts automatically in the background. The frontend refreshes live over a WebSocket connection (`/ws`), with REST polling as a fallback for slower-moving data.

**Mode toggle (top bar):**

| Mode | Description |
|------|-------------|
| `SIM` | Simulation — synthetic prices, rule-based decisions, no API costs |
| `PAPER` | Real yfinance prices, rule-based decisions, no LLM |
| `LIVE` | Live — real yfinance prices, Claude Sonnet analysis, web search |

The mode switch takes effect on the next cycle with no restart (`POST /api/control/mode`).

Note: `api/routes/control.py` also exposes `POST /api/control/pause` / `/resume` (the old Dash dashboard's PAUSE button), but pause/resume and the old STEP/RESET actions are not currently wired to any frontend control — they were not ported during the FastAPI/React migration.

---

## Frontend guide

### LIVE tab (`frontend/src/components/live/LiveTab.tsx`)

Sidebar + main layout, driven live by the `/ws` WebSocket snapshot:

**Sidebar**
- **Portfolio** — current value, P&L since inception, and a survival gauge (SAFE/DEAD, buffer above the death threshold)
- **Agent State** — current emotion (derived by `api/serializers.py::_derive_emotion`) with a quote
- **Agents · Last Cycle** — one card per specialist vote (action, confidence bar, short reasoning excerpt), plus an ARBITRATION card with the final decision
- **Metrics** — Cash / Peak Value / Positions / Hold Streak grid
- **Positions** — one row per open position with allocation bar and P&L%

**Main column**
- **Equity Curve** — inline SVG area chart (`EquityChart.tsx`) with high/low/current markers
- **Activity Log** — live feed of agent actions, newest first, tagged by type (`EXEC`, `ARB`, `TECH`, `ANLST`, `RISK`, `MACRO`, `SL`, `EVAL`, `MEM`, `INFO`/`WARN`/`ERROR`/`CRIT`)

### ANALYTICS tab (`frontend/src/components/analytics/AnalyticsTab.tsx`)

- **KPI grid** — Portfolio Value, Total P&L, Open Positions, Agent Cycle, Hold Streak, Mode, Peak Value, Death Threshold
- **Agent Accuracy** — per-agent market-validated accuracy (`⏳ CALIBRATING` until ≥5 evaluated votes, then `✓ VALIDATED`), plus the current cycle's raw votes
- **Postmortem** — closed-trade lessons and current open-position detail

### BACKTEST tab

Placeholder ("coming soon") in the current frontend — `core/backtest.py`'s `run_backtest()` / `compare_strategies()` functions still exist and are covered by tests, but the tab isn't wired up in the React UI yet.

### TERMINAL tab (`frontend/src/components/terminal/TerminalTab.tsx`)

Bloomberg-style market terminal with live data from the `market_data` package.

```
┌────────────────────────────────────────────────┐
│ TERMINAL                                       │
├────────────────────────────────────────────────┤
│ VIX 18.50 ▼-2.1% │ SPY 512.3 ▲+0.8% │ DXY... │
├────────────────┬───────────────────────────────┤
│ WATCHLIST      │  NEWS — AAPL                  │
│ [AAPL x][TSLA] │  + Apple beats estimates...   │
│ SCREENER       │  - Market volatility rises    │
│ RSI [30──70]   │  ~ Trading volume normal      │
└────────────────┴───────────────────────────────┘
```

- **Macro bar** — VIX, SPY, DXY with price + change %; refreshes every 60s
- **Watchlist** — add/remove symbols, table with price, RSI, MA20, volume; refreshes every 10s
- **Screener** — filter by RSI range, CHG%, MA20, volume; runs on demand
- **News feed** — latest headlines for the selected symbol with sentiment indicator; refreshes every 120s

---

## Simulation vs Live mode

| Aspect | Simulation | Live |
|--------|-----------|------|
| Prices | Random-walk (`SIM_DRIFT`, `SIM_VOLATILITY`) | yfinance real-time |
| News | Template-generated | yfinance headlines |
| Sentiment | Random [-1, 1] | Twitter/X via tweepy (optional) |
| Decisions | RSI rule-based | Claude Sonnet + web search |
| Memory | Rule-generated lessons | Claude Haiku lesson extraction |
| Database | `trades_sim.db` | `trades.db` |
| Cycle interval | 3s | 30s (configurable via `AGENT_INTERVAL`) |
| API costs | None | ~$0.01-0.05 per cycle |

Toggle from the frontend topbar — takes effect on the next cycle.

---

## LangGraph Studio

The graph is registered in `langgraph.json` and can be explored visually:

```bash
# Launch Studio
uv run langgraph dev
```

This opens the Studio UI where you can inspect node inputs/outputs, replay traces, and step through the graph manually — useful for debugging the LLM prompts or the routing logic.

---

## Extending the project

### Add a new node

```python
# In agents/shared/nodes.py — define the node
def my_node(state: AgentState) -> dict:
    return {"log": [_entry("my_node ran")], "confidence": 0.9}

# In agents/multi.py — wire it into the graph
g.add_node("my_node", my_node)
g.add_edge("arbitrate", "my_node")
g.add_edge("my_node", "risk_check")
```

### Add a new specialist agent

1. Create the Pydantic model in `agents/shared/schemas.py`
2. Add the node function in `agents/multi.py`
3. Add it to the `Send()` fan-out in `_route_to_agents()`
4. Add an edge to `arbitrate`
5. Update `WEIGHTS` dict and `agents/registry.py` description

### Add a new ticker

```python
# In config.py
WATCHLIST = ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA", "NVDA"]
```

Simulation mode will auto-seed prices for it. Live mode will fetch via yfinance.

### Change the agent personality

Main system prompt text for the simple graph’s analyze step lives in `agents/shared/prompts.py` (`ANALYZE_SYSTEM_PROMPT`, versioned with `PROMPT_VERSION`). Multi-agent prompts remain in `agents/multi.py` as today.

### Adjust simulation parameters at runtime

In simulation mode, `_sim_mode` is a shared dict. You can expose `SIM_VOLATILITY` and `SIM_DRIFT` through a new `api/routes/control.py` endpoint and write to it directly — no restart needed.

---

## Dependencies

| Package | Role |
|---------|------|
| `anthropic` | Claude API — Sonnet for analysis, Haiku for memory |
| `langgraph` | Agent graph orchestration |
| `yfinance` | Real-time price and news data |
| `fastapi` + `uvicorn` | REST + WebSocket backend |
| `pydantic` | LLM output validation + FastAPI request/response models |
| `httpx` | HTTP client with timeouts for Anthropic SDK |
| `tweepy` | Twitter/X sentiment (optional) |
| `python-dotenv` | `.env` loading |

**Dev tools:** `pytest`, `pytest-cov`, `black`, `ruff`, `pre-commit`

**Frontend (`frontend/package.json`):** React 18, Vite, TypeScript, Vitest

---

## License

MIT
