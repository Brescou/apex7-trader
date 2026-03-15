# Changelog

## [Unreleased]

No uncommitted changes.

## [2026-03-14] — Sprint 5b: Complete Repo Migration

### Added
- `agents/` package: `simple.py`, `multi.py`, `shared/state.py`, `shared/nodes.py`
- `dashboard/` package: `server.py`, `layout.py`, `callbacks/` (6 modules)
- `docs/CLAUDE.md` — copy of root CLAUDE.md with Sprint 5b paths and pitfalls

### Changed
- `agent.py` → `agents/simple.py` + `agents/shared/`
- `agent_multi.py` → `agents/multi.py` + `agents/shared/`
- `app.py` → `dashboard/` package
- `core/registry.py` updated to import from `agents.*`
- `main.py` updated to import from `dashboard`

### Removed
- `agent.py` (migrated)
- `agent_multi.py` (migrated)
- `app.py` (migrated)
- `dashboard_split_plan.md` (temp file)

## [2026-03-14] — Sprint 5: Restructuration + Terminal étendu + CI/CD

### Changed
- Repo structure: `data.py` → `core/data.py`, `backtest.py` → `core/backtest.py`, `graph_registry.py` → `core/registry.py`
- `ARCHITECTURE.md`, `CHANGELOG.md`, `README.md` moved from root to `docs/`
- `docs/` folder created; root `README.md` remains as a copy for GitHub rendering

### Added
- Terminal sparklines: `market_data.fetch_sparkline()` — 1-day hourly OHLC per symbol, 5-min cache; rendered as 40px mini chart per watchlist row
- Price alerts: set ABOVE/BELOW thresholds per symbol, flash banner on trigger, auto-remove after 5s
- Multi-symbol comparison chart: normalized to 100 at start, period selector (1d/5d/1mo/3mo), collapsible panel
- CSV export for watchlist (symbol, price, change_pct, rsi_14, volume, timestamp)
- `market_data.fetch_comparison(symbols, period)` — normalized-to-100 daily closes, 5-min cache
- CI/CD: `.github/workflows/ci.yml` (GitHub Actions — ruff lint, black check, smoke tests, terminal tests)
- `.pre-commit-config.yaml` (ruff + black + standard hooks)
- `pyproject.toml`: `[tool.black]`, `[tool.ruff]` sections + dev dependency group (black, ruff, pre-commit)
- `tests/test_terminal.py` — 7 market data regression tests (fetch_macro, fetch_watchlist_prices, fetch_news, run_screener, fetch_sparkline, fetch_comparison, cache_behavior)
- `core/__init__.py` package marker

## [2026-03-14] — Sprint 4: Solidification

### Changed
- `data.py`: LiveFeed wired into Portfolio.fetch_prices() with fast_info fallback
- `data.py`: Portfolio persistence — atomic JSON save/load (save_state/load_state)
- `backtest.py`: real yfinance data engine (fetch_historical, compute_indicators, run_backtest, compare_strategies)
- `app.py`: BACKTEST tab rewritten with symbol/period/strategy controls, equity curve, trade markers

### Added
- `tests/test_smoke.py`: 9 regression smoke tests
- `config.py`: USE_LIVEFEED, PORTFOLIO_STATE_PATH, PORTFOLIO_SAVE_ENABLED
- `.gitignore`: portfolio_state.json

## [2026-03-14] — Sprint 3: Bloomberg Terminal Tab

### Added
- `market_data.py`: standalone market data module (fetch_macro, fetch_watchlist_prices, fetch_news, run_screener)
- TERMINAL tab in Dash dashboard (8th tab): macro bar, watchlist, screener, news feed
- In-memory cache: 60s macro / 10s watchlist prices
- `MACRO_SYMBOLS`, `MARKET_DATA_CACHE_SEC`, `WATCHLIST_CACHE_SEC`, `NEWS_MAX_ITEMS` config constants

## [2026-03-07] — Stop-loss enforcement + portfolio persistence + dynamic agent weights + real backtest/leaderboard engines

- `agent.py` / `execute_node`: stop-loss pre-check loop runs before agent decision — all open positions checked against `STOP_LOSS_PCT` (5%); triggers immediate SELL with slippage if threshold breached
- `data.py`: `buy()` now returns `{"success": False, "error": "position already open"}` on duplicate (was bare `return None`); added `peak_value` attribute maintained in `record_value()`; added `save_state(path)` / `load_state(path)` for JSON persistence to `.apex7_state.json`
- `agent.py`: `save_state` called after each successful BUY or SELL; `_state["thinking"]` set `True`/`False` around `graph.invoke()` so the SEARCHING badge activates correctly
- `agent_multi.py`: added `_compute_dynamic_weights(db_path)` — 70/30 blend of static weights + accuracy-based weights from last 50 scored `agent_memory` votes per agent; result cached for 10 minutes; `arbitrate_node` uses dynamic weights instead of static `WEIGHTS`
- `backtest.py` (new): `BacktestEngine` — fully autonomous GBM+RSI simulation (4 scenarios: Bull/Bear/High Vol/Flat); computes return_pct, Sharpe, max drawdown, win rate, trade count, portfolio history; no imports from `agent.py`
- `leaderboard.py` (new): `Leaderboard.run_all(scenario)` — runs `BacktestEngine` for CONSERVATIVE (15%), BALANCED (25%), AGGRESSIVE (40%), APEX-7 (config default); ranks by return_pct
- `app.py`: BACKTEST and LEADERBOARD tabs now call real `BacktestEngine` / `Leaderboard` instead of hardcoded placeholders; analytics win_rate fixed to pair BUY/SELL for actual P&L; `_rgba(hex, alpha)` helper added for Plotly `fillcolor` values; `dcc.Collapse` replaced with `html.Div(style={"display":"none"})` toggle; `peak_value` read from `Portfolio` attribute (O(1)) instead of `max(value_history)` scan

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
