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
8. [Dashboard guide](#dashboard-guide)
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

### Simple graph (`AGENT_GRAPH=simple`)

```
┌─────────────────────────────────────────────────────────────┐
│                   dashboard/ (Dash)                          │
│  LIVE · ANALYTICS · BACKTEST · LEADERBOARD · HEATMAP ·      │
│  AGENTS · TERMINAL                                          │
│  dcc.Interval (2s) → callbacks → portfolio state display    │
└──────────────────────────┬──────────────────────────────────┘
                           │ reads
┌──────────────────────────▼──────────────────────────────────┐
│                   Portfolio (core/data.py)                    │
│  Thread-safe state: cash, positions, value_history, logs     │
└──────────────────────────┬──────────────────────────────────┘
                           │ managed by
┌──────────────────────────▼──────────────────────────────────┐
│            Agent loop (dashboard/controller.py)              │
│  pause / step / reset controls via shared _ctrl dict         │
└──────────────────────────┬──────────────────────────────────┘
                           │ invokes
┌──────────────────────────▼──────────────────────────────────┐
│         LangGraph compiled graph (agents/simple.py)          │
│                                                             │
│  __start__                                                  │
│      │                                                      │
│  load_memory   ← SQLite (last 20 trades + patterns)         │
│      │                                                      │
│  fetch_data    ← yfinance prices + news + Twitter sentiment  │
│      │                                                      │
│  analyze       ← Claude Sonnet 4.5 + web_search tool        │
│      │                                                      │
│   conf ≥ 0.7 ──────────────────────────┐                   │
│      │                                  │                   │
│  research      ← Claude Sonnet + web    │                   │
│   (max 2×)                              │                   │
│      │──────────────────────────────────┘                   │
│      │                                                      │
│  risk_check    ← pure Python rules                          │
│      │                                                      │
│  pass ──► execute  ──► save_memory ← Claude Haiku 4.5       │
│  fail ──► skip                                              │
│                                                             │
│  __end__                                                    │
└─────────────────────────────────────────────────────────────┘
```

### Multi-agent graph (`AGENT_GRAPH=multi`)

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
┌──────────────────────────────────────────────────┐
│  trades.db (live) / trades_sim.db (simulation)    │
│  tables: trades, patterns, agent_memory, postmortem│
│  WAL mode + busy_timeout=5000ms                   │
│  All access via _db_write() / _db_read()          │
└──────────────────────────────────────────────────┘
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

**API safety**: a circuit breaker pauses calls after 3 consecutive failures (5 min cooldown). A daily token budget cap (500K tokens) prevents runaway costs. The counter resets at midnight.

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

The `Portfolio` object lives in the main process and is accessed by both the agent thread and the Dash callback thread. All mutations are protected by `threading.RLock()`. The agent's `AgentState` (the LangGraph state dict) is a snapshot passed per-cycle; the portfolio is the source of truth for the dashboard.

This separation means:
- The dashboard can read portfolio state at any time without blocking the agent
- The agent can be paused, stepped, or reset without touching the graph internals

### SQLite for memory

SQLite was chosen over a vector database because:
- The trade history is small and structured (rows, not embeddings)
- SQL filters and sorts (last 20 trades, patterns by timestamp) are exactly what's needed
- Zero infrastructure — the file lives next to the code, auto-created on first access

All writes go through `_db_write()` / `_db_write_multi()` (retries, context managers, logging). All reads through `_db_read()`. Both use `_get_db_path()` to route to the correct sim/live database. WAL mode and `busy_timeout=5000ms` handle concurrent access from the agent, postmortem, and dashboard threads.

### Dash for the dashboard

Dash was chosen over a web framework + frontend for a single reason: **everything stays in Python**. The UI is split across the `dashboard/` package with no HTML/CSS/JS files, no bundler, no separate frontend process.

Key Dash patterns used:
- `dcc.Interval` (2s) for live polling — simpler and more reliable than WebSockets for this use case
- `dcc.Store` for shared client-side state (pause/mode) without server round-trips
- `suppress_callback_exceptions=True` + dynamic tab rendering via a single `tab-content` div
- All CSS inline in `dashboard/server.py`'s `index_string` — no `assets/` directory

---

## Project structure

```
apex7-trader/
├── main.py                         # Entrypoint: app.run()
├── config.py                       # All constants, loaded from .env
├── market_data.py                  # Standalone market data (fetch_macro, sparkline, etc.)
├── leaderboard.py                  # Benchmarks 4 allocation strategies
├── langgraph.json                  # LangGraph Studio config
├── pyproject.toml                  # Dependencies (uv) + black/ruff/pytest config
│
├── agents/                         # Agent graphs and shared logic
│   ├── simple.py                   # Simple graph (1 LLM agent)
│   ├── multi.py                    # Multi-agent graph (4 specialists + arbitration)
│   └── shared/
│       ├── state.py                # AgentState, MultiAgentState TypedDicts
│       ├── nodes.py                # Shared nodes, DB helpers, sim engine, _llm()
│       └── schemas.py              # Pydantic validation for all LLM outputs
│
├── core/                           # Domain logic (no UI, no agents)
│   ├── data.py                     # Portfolio (thread-safe), LiveFeed
│   ├── backtest.py                 # BacktestEngine + run_backtest()
│   ├── indicators.py               # Canonical RSI implementation
│   └── registry.py                 # Graph ID → builder map
│
├── dashboard/                      # Dash UI
│   ├── __init__.py                 # create_app() entry point
│   ├── server.py                   # Dash() init, design tokens, /health endpoint
│   ├── controller.py               # Agent loop, portfolio state, postmortem thread
│   ├── layout/                     # UI layout components
│   │   ├── main.py                 # app.layout builder
│   │   ├── live_tab.py             # Live tab layout
│   │   ├── analytics_tab.py        # Analytics tab layout
│   │   ├── terminal_tab.py         # Terminal tab layout
│   │   ├── helpers.py              # Shared UI helpers (agent cards, trade tables)
│   │   ├── emotions.py             # Emotion system (icon/color/quote mapping)
│   │   └── classify.py             # Log badge classification
│   └── callbacks/                  # Dash callbacks (one file per tab)
│       ├── live.py                 # Live tab + tab routing
│       ├── analytics.py            # Analytics tab
│       ├── backtest_tab.py         # Backtest tab
│       ├── leaderboard_tab.py      # Leaderboard tab
│       ├── heatmap.py              # Heatmap tab
│       ├── agents.py               # Agents tab
│       └── terminal.py             # Terminal tab (16 callbacks)
│
├── docs/
│   ├── ARCHITECTURE.md
│   └── CHANGELOG.md
│
├── tests/
│   ├── conftest.py                 # Pytest fixtures (sim_mode, portfolio, tmp_db)
│   ├── test_smoke.py               # 9 regression smoke tests
│   ├── test_integration.py         # 14 integration tests (LLM mocks, schema validation)
│   └── test_terminal.py            # 7 market data tests
│
├── .github/workflows/ci.yml        # CI: ruff + black + pytest
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
SIMULATION_MODE=true        # true = no real money, no API calls for data
SIM_VOLATILITY=0.02         # price volatility per step (default 2%)
SIM_DRIFT=0.0001            # slight upward drift (default 0.01%)
AGENT_GRAPH=multi           # "simple" (default) or "multi"
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
# Start the dashboard + agent
uv run python main.py

# Run all tests (30 tests)
uv run pytest tests/ -v

# Run smoke tests only (legacy runner)
uv run python tests/test_smoke.py

# Lint
uv run ruff check . --select E,F,W --ignore E501

# Format check
uv run black --check .
```

Open **http://localhost:8050** in your browser.

The agent starts automatically in the background. The dashboard refreshes every 2 seconds.

**Control buttons (top bar):**

| Button | Action |
|--------|--------|
| `PAUSE` | Suspends the agent between cycles (yellow when active) |
| `STEP` | Runs exactly one cycle then pauses |
| `RESET` | Kills the current agent and starts a fresh portfolio |

**Mode toggle (top bar):**

| Mode | Description |
|------|-------------|
| `SIM` | Simulation — synthetic prices, rule-based decisions, no API costs |
| `LIVE` | Live — real yfinance prices, Claude Sonnet analysis, web search |

The mode switch takes effect on the next cycle with no restart.

---

## Dashboard guide

### LIVE tab

Two-column layout:

**Left column (280px)**
- **Portfolio Value** — current total with P&L, health bar (gradient red→blue→green scaled to $0–$2000)
- **Agent State** — current emotion (EUPHORIC / EXCITED / FOCUSED / CALM / NERVOUS / PANIC / DESPERATE) with quote, and a "SEARCHING..." badge when the LLM is active
- **Metrics** — Cash / Invested / Peak / Drawdown grid
- **Open Positions** — up to 3 cards with per-position P&L, price, and a mini bar
- **Agent Track Records** — accuracy badges per agent (multi mode only)

**Right column**
- **Equity Curve** — Plotly sparkline with death floor and start reference lines
- **Activity Log** — live feed of agent actions, newest first, color-coded by type:

| Badge | Color | Meaning |
|-------|-------|---------|
| `BUY` | Blue | Buy order executed |
| `SELL WIN` | Green | Sell at profit |
| `SELL LOSS` | Red | Sell at loss |
| `HOLD` | Gray | No trade this cycle |
| `AI` | Purple | LLM call / web search |
| `INTEL` | Purple | Market analysis output |
| `TECH` | Blue | Technician agent vote |
| `ANLST` | Cyan | Analyst agent vote |
| `RISK` | Red | Risk manager assessment |
| `MACRO` | Yellow | Macro watcher regime |
| `ARBIT` | Green | Arbitration decision |
| `SIM` | Orange | Simulation engine event |
| `ERR` | Orange | Error |
| `DEATH` | Red | Portfolio killed |

**Death state:** when portfolio ≤ $50, the page background shifts to near-black red, the status dot turns red, and the left column shows a termination screen.

**Agent cards panel (multi mode only):**
- TECH / ANLST / RISK / MACRO cards, each collapsible with vote details
- ARBITRATION card always visible below

### ANALYTICS tab

Loads from `trades.db` on render (auto-refreshes every 30s or on manual refresh).

- **KPI row** — Win Rate, Avg P&L, Best/Worst Trade, Total Trades, Avg Confidence, Favourite Ticker, Sim/Live ratio
- **Charts (2x2)** — P&L by ticker (bar), Action distribution (donut), Confidence over time (line), Trades by hour (bar)
- **Trade table** — full history with sort, filter, pagination (20/page), conditional row coloring

### BACKTEST tab

Enter a symbol (e.g. `AAPL`), select a period (1mo / 3mo / 6mo / 1y) and a strategy (`simple` / `multi`), click **RUN BACKTEST**.

Runs `run_backtest()` from `core/backtest.py` against real yfinance data — no LLM calls, deterministic rules only.

Output: KPI row (total return, vs SPY benchmark, win rate, max drawdown, Sharpe ratio) + equity curve with SPY overlay and BUY/SELL trade markers + trade log table.

### LEADERBOARD tab

Select a scenario, click **RUN ALL AGENTS**.

Runs `Leaderboard().run_all(scenario)` — benchmarks 4 allocation strategies (CONSERVATIVE 15%, BALANCED 25%, AGGRESSIVE 40%, APEX-7 default) through 80 cycles each.

Output: ranked table (winner highlighted in green) + comparative returns bar chart with breakeven line.

### HEATMAP tab

Per-symbol performance matrix showing returns and trade frequency across the watchlist.
Data sourced from `trades.db`.

### AGENTS tab

Per-agent comparison table loaded from `agent_memory` in `trades.db`:
- Accuracy rate (correct votes / total votes)
- Average confidence
- Win rate per agent

### TERMINAL tab

Bloomberg-style market terminal with live data from `market_data.py`.

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

Toggle live from the dashboard — takes effect on the next cycle.

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

# In agents/simple.py — wire it into the graph
g.add_node("my_node", my_node)
g.add_edge("analyze", "my_node")
g.add_edge("my_node", "risk_check")
```

### Add a new specialist agent (multi graph)

1. Create the Pydantic model in `agents/shared/schemas.py`
2. Add the node function in `agents/multi.py`
3. Add it to the `Send()` fan-out in `_route_to_agents()`
4. Add an edge to `arbitrate`
5. Update `WEIGHTS` dict and `core/registry.py` description

### Add a new ticker

```python
# In config.py
WATCHLIST = ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA", "NVDA"]
```

Simulation mode will auto-seed prices for it. Live mode will fetch via yfinance.

### Change the agent personality

The system prompt is in `analyze_node` in `agents/shared/nodes.py`. Edit the `system` string to change how the agent reasons, its risk appetite, or its output format.

### Adjust simulation parameters at runtime

In simulation mode, `_sim_mode` is a shared dict. You can expose `SIM_VOLATILITY` and `SIM_DRIFT` as Dash sliders and write to it directly — no restart needed.

---

## Dependencies

| Package | Role |
|---------|------|
| `anthropic` | Claude API — Sonnet for analysis, Haiku for memory |
| `langgraph` | Agent graph orchestration |
| `yfinance` | Real-time price and news data |
| `dash` + `plotly` | Terminal dashboard + charts |
| `pydantic` | LLM output validation |
| `httpx` | HTTP client with timeouts for Anthropic SDK |
| `tweepy` | Twitter/X sentiment (optional) |
| `python-dotenv` | `.env` loading |

**Dev tools:** `pytest`, `pytest-cov`, `black`, `ruff`, `pre-commit`

---

## License

MIT
