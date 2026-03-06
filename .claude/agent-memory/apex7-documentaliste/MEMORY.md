# APEX-7 Documentaliste — Agent Memory

## Project state (as of 2026-03-06)

### Files committed
- `README.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, `CLAUDE.md` exist and are up to date.
- Commit: `ce7fce3 docs: update documentation post-feature`

### Pending features (not yet in code, pending tasks)
- `stoploss_guard` node in `agent_multi.py` — task #2
- Devil's Advocate agent (5th specialist) in `agent_multi.py` — task #2
- Watchlist UI, stop-loss banner, devil card in `app.py` — task #3
- HISTORY tab in `app.py` — task #3

### What IS in code (unstaged changes)
- `config.py`: `STOP_LOSS_PCT = 0.05` (hardcoded, not env var)
- `data.py`: `LiveFeed` class — fetches 1m yfinance history for multi-symbol lists; NOT wired into any graph node
- `agent_multi.py`: 4 specialists only (technician, analyst, risk_manager, macro_watcher) — no devil's advocate yet
- `app.py`: 4 tabs (LIVE, ANALYTICS, BACKTEST, LEADERBOARD) — no HISTORY tab yet; agent cards panel for multi mode exists

## Known pitfalls

- `graph_registry.py` describes multi as "4 Specialists" — must update to "5 Specialists" when devil's advocate is added
- `LiveFeed` and `STOP_LOSS_PCT` are defined but not wired into any node — document as such, don't claim they're active
- `save_memory_node` skips HOLD actions — only BUY/SELL land in SQLite
- `research` in multi-graph goes directly to `risk_check` (not looping back to `arbitrate` like simple graph loops to `analyze`)
- `start_agent()` in `agent.py` is not used by `app.py` — `app.py` has its own `_agent_loop`
- No `assets/` directory — all CSS inline in `app.py` `index_string`
- `avg_price` vs `avg_cost` — both handled in `_portfolio_value()` for backward compat

## Architecture constants
- Simple graph confidence threshold: 0.70
- Multi-agent graph confidence threshold: 0.72
- Agent weights: technician=0.30, analyst=0.35, risk_manager=0.20, macro_watcher=0.15
- LangGraph Studio IDs: `apex7_simple`, `apex7_multi`

## Conventions
- Prompts in French — intentional, do not translate
- All CSS inline in `app.py` — no `assets/` folder
- Design tokens at top of `app.py` (BG_DEEP, GREEN, RED, BLUE, etc.)
