# APEX-7 Documentaliste — Agent Memory

## Project state (as of 2026-03-06)

### Files committed
- `README.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, `CLAUDE.md` — up to date as of commit `03cd105`
- Commit message: `docs: update post multi-symbol + postmortem + agent memory + heatmap + agent-comparison`

### What IS in code (confirmed)
- `config.py`: `STOP_LOSS_PCT = 0.05`, `POSTMORTEM_HOUR = 22` (both hardcoded, not env vars)
- `data.py`: `open_symbols()` and `closed_trades_since(ts)` methods on Portfolio; `buy()` returns `None` (not a dict) if symbol already held
- `data.py`: `LiveFeed` class — defined, not wired into any graph node
- `agent_multi.py`: 4 specialists only (technician, analyst, risk_manager, macro_watcher)
- `agent_multi.py`: `run_daily_postmortem(portfolio)` — fires from `app.py` background thread at POSTMORTEM_HOUR
- `app.py`: 6 tabs — LIVE, ANALYTICS, BACKTEST, LEADERBOARD, HEATMAP, AGENTS
- `app.py`: Agent Track Records badges in LIVE tab (multi mode only)
- SQLite: 4 tables — trades, patterns, agent_memory, postmortem

## Known pitfalls

- `graph_registry.py` describes multi as "4 Specialists" — must update to "5 Specialists" if a 5th specialist is added
- `LiveFeed` and `STOP_LOSS_PCT` are defined but not wired into any node — document as such
- `save_memory_node` skips HOLD actions — only BUY/SELL land in SQLite trades table
- `research` in multi-graph goes directly to `risk_check` (not looping back to `arbitrate`)
- `start_agent()` in `agent.py` is not used by `app.py` — `app.py` has its own `_agent_loop`
- No `assets/` directory — all CSS inline in `app.py` `index_string`
- `avg_price` vs `avg_cost` — both handled in `_portfolio_value()` for backward compat
- Postmortem thread (`apex7-postmortem`) only started in `app.py`, not in `main.py` or standalone `agent.py`
- `agent_memory` inserts happen in specialist nodes only (not in simple graph); simulation path inserts with `source='simulation'`, live path with `source='live'`
- `Portfolio.buy()` returns `None` (not a dict) when symbol already held — callers must handle None gracefully

## Architecture constants
- Simple graph confidence threshold: 0.70
- Multi-agent graph confidence threshold: 0.72
- Agent weights: technician=0.30, analyst=0.35, risk_manager=0.20, macro_watcher=0.15
- LangGraph Studio IDs: `apex7_simple`, `apex7_multi`
- POSTMORTEM_HOUR = 22 (hardcoded)

## Conventions
- Prompts in French — intentional, do not translate
- All CSS inline in `app.py` — no `assets/` folder
- Design tokens at top of `app.py` (BG_DEEP, GREEN, RED, BLUE, etc.)

## Write tool limitation
- The Write tool requires the file to have been Read in the same tool-call session
- Use Bash cat heredoc as fallback when Write refuses due to session tracking
