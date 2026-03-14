# APEX-7 // SURVIVAL TRADER

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

```
┌─────────────────────────────────────────────────────────────┐
│                        app.py (Dash)                        │
│  LIVE · ANALYTICS · BACKTEST · LEADERBOARD · HEATMAP · AGENTS · TERMINAL│
│  dcc.Interval (2s) → callbacks → portfolio state display    │
└──────────────────────────┬──────────────────────────────────┘
                           │ reads
┌──────────────────────────▼──────────────────────────────────┐
│                     Portfolio (data.py)                      │
│  Thread-safe state: cash, positions, value_history, logs     │
└──────────────────────────┬──────────────────────────────────┘
                           │ managed by
┌──────────────────────────▼──────────────────────────────────┐
│               Agent loop (app.py background thread)          │
│  pause / step / reset controls via shared _ctrl dict         │
└──────────────────────────┬──────────────────────────────────┘
                           │ invokes
┌──────────────────────────▼──────────────────────────────────┐
│              LangGraph compiled graph (agent.py)             │
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
                           │ persists
┌──────────────────────────▼──────────────────────────────────┐
│                      trades.db (SQLite)                      │
│  tables: trades, patterns, agent_memory, postmortem          │
└─────────────────────────────────────────────────────────────┘
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
| Market analysis + research | `claude-sonnet-4-5` | Complex reasoning, web search, JSON output |
| Memory pattern extraction | `claude-haiku-4-5` | Fast, cheap — runs on every cycle |
| Trade lesson generation | `claude-haiku-4-5` | Short text, latency-sensitive |

This keeps the expensive model where reasoning quality matters and the cheap model for boilerplate LLM work.

### Web search as a native tool

Claude's `web_search_20250305` tool is used directly via the Anthropic SDK in an agentic loop — not as a LangChain wrapper. The `_llm()` helper handles the tool-use cycle (up to 8 iterations) and returns the final assistant text. This gives the agent real-time market intel without maintaining a separate search API integration.

### Simulation mode

A full simulation engine runs with zero network calls:
- Prices follow a configurable random-walk (`SIM_DRIFT`, `SIM_VOLATILITY`)
- RSI is computed from the simulated price history
- Decisions are rule-based (oversold → BUY, overbought → SELL, else HOLD)
- No LLM is called in simulation mode

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
- Zero infrastructure — the file lives next to the code, `trades.db` is auto-created

Pattern extraction (turning raw trades into reusable lessons) is done by Haiku over the last 10 trades per cycle. In simulation mode this is skipped; lessons are generated as rule-based strings.

### Dash for the dashboard

Dash was chosen over a web framework + frontend for a single reason: **everything stays in Python**. The entire UI — layout, styling, charts, callbacks — is defined in one file (`app.py`) with no HTML/CSS/JS files, no bundler, no separate frontend process.

Key Dash patterns used:
- `dcc.Interval` (2s) for live polling — simpler and more reliable than WebSockets for this use case
- `dcc.Store` for shared client-side state (pause/mode) without server round-trips
- `suppress_callback_exceptions=True` + dynamic tab rendering via a single `tab-content` div
- All CSS in `index_string` (inline in Python) — no `assets/` directory

---

## Project structure

```
apex7-trader/
├── agent.py           # Simple graph: all nodes, simulation engine, _llm helper
├── agent_multi.py     # Multi-agent graph: 4 specialists + arbitration + run_daily_postmortem
├── app.py             # Dash app — layout, callbacks, UI helpers
├── backtest.py        # BacktestEngine — real yfinance backtest (fetch_historical, compute_indicators, run_backtest, compare_strategies) + legacy GBM scenarios
├── leaderboard.py     # Leaderboard — ranks 4 agent configs via BacktestEngine
├── market_data.py     # Standalone market data module — fetch_macro, fetch_watchlist_prices, fetch_news, run_screener
├── config.py          # All configuration constants, loaded from .env
├── data.py            # Portfolio class + LiveFeed — thread-safe state, buy/sell/log
├── graph_registry.py  # Maps graph IDs ("simple"/"multi") to builder functions
├── main.py            # Entrypoint: app.run()
├── langgraph.json     # LangGraph Studio config — exposes both graphs
├── pyproject.toml     # Dependencies (uv)
├── tests/
│   └── test_smoke.py  # 9 regression smoke tests — no pytest, assert+print, exit 0/1
├── .env               # API keys (not committed)
├── portfolio_state.json  # Portfolio snapshot — written on every trade (not committed)
└── trades.db          # SQLite — auto-created on first run (not committed)
```

---

## Installation

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
# Clone the repository
git clone <repo-url>
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
STOP_LOSS_PCT   = 0.05      # stop-loss threshold (5%) — enforced in execute_node before agent decision
POSTMORTEM_HOUR = 22        # hour (0-23) at which daily postmortem runs
```

---

## Running the project

```bash
# Start the dashboard + agent
uv run python main.py

# Run regression smoke tests (9 tests, no pytest required)
uv run python tests/test_smoke.py
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
- **Charts (2×2)** — P&L by ticker (bar), Action distribution (donut), Confidence over time (line), Trades by hour (bar)
- **Trade table** — full history with sort, filter, pagination (20/page), conditional row coloring

### BACKTEST tab

Enter a symbol (e.g. `AAPL`), select a period (1mo / 3mo / 6mo / 1y) and a strategy (`simple` / `multi`), click **RUN BACKTEST**.

Runs `run_backtest()` from `backtest.py` against real yfinance data — no LLM calls, deterministic rules only.

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
│ [AAPL ×][TSLA] │  🟢 Apple beats estimates...  │
│ SCREENER       │  🔴 Market volatility rises   │
│ RSI [30──70]   │  ⚪ Trading volume normal     │
└────────────────┴───────────────────────────────┘
```

- **Macro bar** — VIX, SPY, DXY with price + change %; refreshes every 60s
- **Watchlist** — add/remove symbols, table with price, RSI, MA20, volume; refreshes every 10s
- **Screener** — filter by RSI range, CHG%, MA20, volume; runs on demand
- **News feed** — latest headlines for the selected symbol with sentiment indicator; refreshes every 120s

---

## LangGraph Studio

The graph is registered in `langgraph.json` and can be explored visually:

```bash
# Install LangGraph CLI if needed
uv add langgraph-cli

# Launch Studio
uv run langgraph dev
```

This opens the Studio UI where you can inspect node inputs/outputs, replay traces, and step through the graph manually — useful for debugging the LLM prompts or the routing logic.

---

## Extending the project

### Add a new node

```python
# In agent.py
def my_node(state: AgentState) -> dict:
    # state is read-only — return only the fields you want to update
    return {"log": [_entry("my_node ran")], "confidence": 0.9}

# Wire it into the graph
g.add_node("my_node", my_node)
g.add_edge("analyze", "my_node")
g.add_edge("my_node", "risk_check")
```

### Add a new ticker

```python
# In config.py
WATCHLIST = ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA", "NVDA"]
```

Simulation mode will auto-seed prices for it. Live mode will fetch via yfinance.

### Change the agent personality

The system prompt is in `analyze_node` in `agent.py`. Edit the `system` string to change how the agent reasons, its risk appetite, or its output format.

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
| `tweepy` | Twitter/X sentiment (optional) |
| `python-dotenv` | `.env` loading |

---

## License

MIT
