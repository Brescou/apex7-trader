# Changelog

## [Unreleased]

No uncommitted changes.

## [2026-03-06] — Multi-symbol + postmortem + agent memory + heatmap + agent comparison

- `data.py`: multi-symbol buy guard — `buy()` returns early if symbol already held; added `open_symbols()` and `closed_trades_since(ts)` methods
- `config.py`: added `POSTMORTEM_HOUR = 22` (hardcoded — triggers daily postmortem batch)
- `agent.py` + `agent_multi.py`: added `agent_memory` and `postmortem` tables to `_SCHEMA`; idempotent via `CREATE TABLE IF NOT EXISTS`
- `agent_multi.py`: added `run_daily_postmortem(portfolio)` — per-symbol postmortem on all SELL trades since midnight; writes P&L, holding duration, agents correct, Haiku-generated summary to `postmortem` table
- `app.py`: HEATMAP tab (5th) — per-symbol return heatmap + trade frequency matrix; AGENTS tab (6th) — per-agent accuracy, confidence, win-rate comparison; Agent Track Records badges in LIVE tab (multi mode only); background `apex7-postmortem` thread fires `run_daily_postmortem` at `POSTMORTEM_HOUR`

## [2026-03-06] — Multi-agent graph with 4 specialized agents + arbitration

- Added `agent_multi.py`: `MultiAgentState`, supervisor node, 4 parallel specialist agents (technician, analyst, risk_manager, macro_watcher), arbitration node
- Added `graph_registry.py`: maps `"simple"` / `"multi"` graph IDs to builder functions
- Added `langgraph.json`: exposes both compiled graphs (`apex7_simple`, `apex7_multi`) to LangGraph Studio
- `app.py`: graph selector dropdown, agent cards panel (per-agent vote header + collapsible body + arbitration card), pause/step/reset controls
- `agent.py`: `_sim_mode` dict, `set_simulation_mode` / `get_simulation_mode`, `sim_research` function, `.env` hot-write on mode toggle
- `config.py`: added `STOP_LOSS_PCT = 0.05`; `data.py`: added `LiveFeed` class (both defined, not yet wired into graph nodes)

## [2026-03-06] — .env.example

- Added `.env.example` with all supported env vars documented

## [2026-03-06] — Initial release

- `agent.py`: LangGraph simple graph — load_memory, fetch_data, analyze (Sonnet + web_search), research loop, risk_check, execute, save_memory (Haiku)
- `app.py`: Dash dashboard with Bloomberg terminal aesthetic — LIVE / ANALYTICS / BACKTEST / LEADERBOARD tabs
- `data.py`: `Portfolio` class with `threading.RLock()` — buy, sell, record_value, check_death
- `config.py`: all constants, env var loading
- `main.py`: entrypoint
- SQLite schema: `trades` and `patterns` tables, `source` column for live/simulation distinction
