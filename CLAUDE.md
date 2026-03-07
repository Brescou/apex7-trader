# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the dashboard + agent (opens http://localhost:8050)
uv run python main.py

# Run a single agent cycle standalone (calls Anthropic + yfinance)
uv run python agent.py

# Launch LangGraph Studio (visual graph debugger)
uv run langgraph dev
```

There is no test suite. The standalone `python agent.py` serves as an integration smoke test for one full cycle.

## Architecture

APEX-7 is a survival trading agent that starts with $1,000 and dies if the portfolio drops below $50. It runs as a background thread behind a Dash dashboard.

### Key files

| File | Role |
|------|------|
| `main.py` | Entrypoint — calls `app.run()` |
| `app.py` | Dash layout, callbacks, and the `_agent_loop` background thread |
| `agent.py` | Simple graph: LangGraph nodes, simulation engine, `start_agent()` |
| `agent_multi.py` | Multi-agent graph: 4 specialized agents + arbitration node + `run_daily_postmortem()` |
| `data.py` | `Portfolio` — thread-safe state (cash, positions, value history, logs); `LiveFeed` — multi-symbol yfinance wrapper |
| `config.py` | All constants, loaded from `.env` |
| `graph_registry.py` | Maps graph IDs (`"simple"` / `"multi"`) to builder functions |
| `langgraph.json` | LangGraph Studio config — exposes both compiled graphs |

### Concurrency model

The Dash callback thread and the agent loop thread share a single `Portfolio` object. All mutations on `Portfolio` are protected by `threading.RLock()`. The agent's `AgentState` is a per-cycle snapshot; `Portfolio` is the source of truth for the dashboard.

A third daemon thread (`apex7-postmortem`) runs in `app.py` and calls `run_daily_postmortem()` once per day at `POSTMORTEM_HOUR`. It only reads `portfolio.trade_history` and writes to SQLite — no Portfolio mutations.

### Two graphs

**Simple graph** (`AGENT_GRAPH=simple`, default):
```
load_memory → fetch_data → analyze → [research loop if conf < 0.70] → risk_check → execute → save_memory
```

**Multi-agent graph** (`AGENT_GRAPH=multi`):
```
load_memory → fetch_data → supervisor → [technician | analyst | risk_manager | macro_watcher] (parallel, via Send) → arbitrate → [research if conf < 0.72] → risk_check → execute → save_memory
```

Nodes shared between both graphs: `load_memory`, `fetch_data`, `risk_check`, `execute`, `save_memory`, `skip`, `research`.

### Model usage

- `claude-sonnet-4-5` — `analyze_node`, `analyst_node`, `arbitrate_node` (complex reasoning + web search)
- `claude-haiku-4-5-20251001` — `load_memory_node` (pattern extraction), `save_memory_node` (lesson generation), `technician_node`, `risk_manager_node`, `macro_watcher_node`, `supervisor_node`

The `_llm()` helper in `agent.py` handles the agentic web-search tool loop (up to 8 iterations) using Claude's `web_search_20250305` tool directly via the Anthropic SDK.

### Simulation mode

When `SIMULATION_MODE=true` (or toggled live from the Dash UI):
- `sim_fetch_data()` / `sim_analyze()` replace real data fetches and LLM calls with a random-walk price engine and RSI-based rule logic
- No Anthropic API calls are made; `trades.db` still records trades with `source='simulation'`
- Cycle interval drops from `AGENT_INTERVAL` (30s) to 3s
- The mode switch takes effect on the next cycle with no restart

### State accumulation pattern

`AgentState` uses `Annotated[List, operator.add]` for `log` and `portfolio_history` fields so nodes can append without overwriting. Nodes return only the fields they modify.

### LLM prompts

System prompts and user messages in `analyze_node`, `research_node`, and the multi-agent nodes are written in French. This is intentional — do not translate them.

### Adding a new graph node

```python
# In agent.py
def my_node(state: AgentState) -> dict:
    return {"log": [_entry("my_node ran")], "confidence": 0.9}

g.add_node("my_node", my_node)
g.add_edge("analyze", "my_node")
g.add_edge("my_node", "risk_check")
```

### SQLite schema

`trades.db` is auto-created at startup. Four tables:

| Table | Description |
|-------|-------------|
| `trades` | One row per executed BUY/SELL trade (HOLD not persisted) |
| `patterns` | Lessons extracted by Haiku after each trade |
| `agent_memory` | One row per agent vote per cycle; `was_correct` updated by `arbitrate_node` |
| `postmortem` | One row per closed trade (SELL); written by `run_daily_postmortem()` |

The `source` column on `trades`, `agent_memory`, and `postmortem` is `'live'` or `'simulation'`.

### LiveFeed

`LiveFeed` in `data.py` provides multi-symbol price fetching using 1m yfinance history. Distinct from `Portfolio.fetch_prices()` (which uses `yf.Tickers` fast_info). Currently defined but not wired into the agent graph.

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

`WATCHLIST`, `INITIAL_BALANCE`, `DEATH_THRESHOLD`, `MAX_POSITIONS`, `MAX_ALLOC_PCT`, `AGENT_INTERVAL`, `STOP_LOSS_PCT`, and `POSTMORTEM_HOUR` are hardcoded in `config.py` and not overridable by env vars.

## Known pitfalls

- **No `assets/` directory** — all CSS is inlined in `app.py`'s `index_string`. Do not create an `assets/` folder expecting Dash to pick it up automatically.
- **`HOLD` trades not saved** — `save_memory_node` returns early on HOLD. Patterns table only contains BUY/SELL lessons.
- **`avg_price` vs `avg_cost`** — both keys appear in `_portfolio_value()` due to backward compat (`pos.get("avg_price", pos.get("avg_cost", 0))`). New positions always use `avg_price`.
- **`trades.db` soft migration** — on startup, `agent.py` tries `ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'live'` and silently catches the error if the column exists. Do not remove this block.
- **`research` in multi-graph goes directly to `risk_check`** — unlike the simple graph where `research` loops back to `analyze`. This is intentional.
- **`LiveFeed` not wired** — `LiveFeed` class exists in `data.py` and `STOP_LOSS_PCT` in `config.py` but neither is used in any graph node yet.
- **graph_registry description outdated** — `graph_registry.py` describes multi as "4 Specialists" — update if a 5th specialist is added.
- **`start_agent()` in `agent.py` is unused from the dashboard** — `app.py` runs its own `_agent_loop` directly, not via `start_agent()`. The function exists for standalone use.
- **Postmortem thread only in `app.py`** — `run_daily_postmortem()` is never called from `main.py` or `agent.py`. It only runs when the full Dash app is started, not from standalone `python agent.py`.
- **`agent_memory` inserts in live path only for specialist nodes** — in simulation mode, `sim_technician`, `sim_analyst`, `sim_risk_manager`, `sim_macro_watcher` each insert into `agent_memory` with `source='simulation'`. In live mode, `technician_node`, `analyst_node`, `risk_manager_node`, `macro_watcher_node` each insert with `source='live'`. The simple graph does not write to `agent_memory` at all.
- **Multi-symbol position limit** — `Portfolio.buy()` silently returns `None` (not a dict) if the symbol is already held. Callers in `execute_node` check `result["success"]` — ensure any new callers handle a `None` return gracefully.

## Code conventions

- All CSS inline as Python dicts — no external stylesheets
- Design tokens defined at top of `app.py` (BG_DEEP, GREEN, RED, etc.) — reuse them everywhere
- Dash callbacks use pattern-matching IDs `{"type": ..., "index": ...}` for agent cards
- Emotion system: `_emotion(total)` derives state from portfolio value ratio; `_EMOTIONS` dict maps to icon/color/quote
- `_classify_v2()` returns `(badge_label, color)` for every log message type — extend it when adding new node types
