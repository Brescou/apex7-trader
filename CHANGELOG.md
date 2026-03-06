# Changelog

## [Unreleased]

Changes detected in working tree (not yet committed):

- `config.py`: added `STOP_LOSS_PCT = 0.05` constant
- `data.py`: added `LiveFeed` class for multi-symbol price fetching via yfinance (1m interval)
- `agent_multi.py`: refactored — 4 specialized agents remain, multi-agent state and routing reviewed
- `app.py`: agent card panel (TECH / ANLST / RISK / MACRO) visible in multi-agent mode with collapsible reasoning blocks

## [2026-03-06] — Multi-agent graph with 4 specialized agents + arbitration

- Added `agent_multi.py`: `MultiAgentState`, supervisor node, 4 parallel specialist agents (technician, analyst, risk_manager, macro_watcher), arbitration node
- Added `graph_registry.py`: maps `"simple"` / `"multi"` graph IDs to builder functions
- Added `langgraph.json`: exposes both compiled graphs (`apex7_simple`, `apex7_multi`) to LangGraph Studio
- `app.py`: graph selector dropdown, agent cards panel (per-agent vote header + collapsible body + arbitration card), pause/step/reset controls
- `agent.py`: `_sim_mode` dict, `set_simulation_mode` / `get_simulation_mode`, `sim_research` function, `.env` hot-write on mode toggle

## [2026-03-06] — .env.example

- Added `.env.example` with all supported env vars documented

## [2026-03-06] — Initial release

- `agent.py`: LangGraph simple graph — load_memory, fetch_data, analyze (Sonnet + web_search), research loop, risk_check, execute, save_memory (Haiku)
- `app.py`: Dash dashboard with Bloomberg terminal aesthetic — LIVE / ANALYTICS / BACKTEST / LEADERBOARD tabs
- `data.py`: `Portfolio` class with `threading.RLock()` — buy, sell, record_value, check_death
- `config.py`: all constants, env var loading
- `main.py`: entrypoint
- SQLite schema: `trades` and `patterns` tables, `source` column for live/simulation distinction
