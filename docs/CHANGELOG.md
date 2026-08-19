# Changelog

## [Unreleased] — FastAPI + React 19 + Mantine 9

### Stack

- **UI:** React 19 + Mantine 9 + Vite (`frontend/`). Backend: FastAPI (`api/`), WebSocket `/ws`.
- **Agent loop:** `runtime/controller.py` (renamed from `dashboard/`). `api/` polls `_state` / `_ctrl`; `start_controller()` runs from the FastAPI lifespan hook.
- **Auth (optional):** set `DASHBOARD_PASSWORD` to gate REST (`Authorization: Bearer …`) and `/ws` (`?token=`). `/health` stays open. Unset = no auth (localhost default). Tests: `tests/test_api.py`.

The original Plotly Dash UI (layout / callbacks / Flask) was removed; those files no longer exist.

### Trading / agents

- Single multi-agent graph (`agents/multi.py`): technician, analyst, risk_manager, macro_watcher, economist, geopolitician + arbitration. The simple graph and `AGENT_GRAPH` toggle are gone.
- Modes: **LIVE** (LLM, 15 min, NYSE/TSX cash hours), **PAPER** (real yfinance prices, rule-based, no LLM, `trades_paper.db`), **SIM** (random walk, `trades_sim.db`). Switch is live via `POST /api/control/mode`.
- Models: `claude-sonnet-5` (analyst, geo, research, arbitrate) + `claude-haiku-4-5-20251001` (other nodes).
- Deferred `was_correct`: `evaluate_pending_trades` scores votes from the real market move after `EVAL_HORIZON_CALENDAR_DAYS` (skipped in SIM). Dynamic agent weights warm up after 5 evaluated votes.
- Partial exits (`sell_pct`), pyramiding (`MAX_PYRAMID_LAYERS`), trailing stop, take-profit, time-stop, drawdown BUY block, earnings hard block.
- LLM cost: web_search loop capped at 2 API turns; economist / geopolitician votes cached 1 h (`SLOW_AGENT_TTL_SEC`).
- Discord (`DISCORD_WEBHOOK_URL`): trades, death, stagnation, rate-limit, startup, daily digest, weekly report, evaluation alerts.

### Data

- `market_data/` package: macro, quotes, news, earnings, charts, sectors, correlation, economic calendar, screener. No imports from `agents/` or `runtime/`. Finnhub (`FINNHUB_API_KEY`) backs quotes when the yfinance breaker is open and company news when `Ticker.news` is empty.
- FRED + CNN Fear & Greed (`core/external_data.py`). Canonical indicators in `core/indicators.py`; Sharpe/Sortino/drawdown/Kelly in `core/metrics.py`.
- Analytics prompt-version A/B stats (`tests/test_prompt_versions.py`).

### Frontend tabs

Live, Terminal, Analytics (`frontend/src/components/{live,terminal,analytics}/`). Terminal: macro bar (VIX / SPY / DXY / F&G / Fed funds / 10Y), watchlist, chart, news (paginated "+ SHOW MORE", 8 at a time), screener, sector heatmap, correlation matrix.

## Earlier work (2026-03 → 2026-05)

LangGraph multi-agent pipeline, SQLite persistence (`trades` / `patterns` / `agent_memory` / `postmortem` / `pending_evaluations` / `watchlist`), thread-safe `Portfolio`, WAL + `_db_read` / `_db_write`, Pydantic LLM schemas, token budget + circuit breaker, CI (ruff / black / pytest / frontend tsc+vitest+build).
