# apex7-frontend Agent Memory

## Project Layout (post Sprint 5b)
- Entry: `main.py` → `from dashboard import create_app; app = create_app()`
- Dashboard package: `dashboard/`
  - `server.py` — Dash app singleton, design tokens, `_rgba()`, `index_string`
  - `controller.py` — `_state`, `_ctrl`, `_agent_loop`, `_launch`, postmortem thread
  - `layout.py` — UI helpers, tab layout functions, `app.layout` assignment
  - `callbacks/` — 7 callback modules (live, analytics, backtest_tab, leaderboard_tab, heatmap, agents, terminal)
  - `__init__.py` — `create_app()` factory
- Agents package: `agents/` (migrated from agent.py/agent_multi.py)
  - `agents.shared.nodes` — `get_simulation_mode`, `set_simulation_mode`
  - `agents.multi` — `run_daily_postmortem`

## Design Tokens (in dashboard/server.py)
BG_DEEP, BG_CARD, BG_HOVER, GREEN, RED, BLUE, ORANGE, YELLOW, PURPLE, GRAY, BORDER, TEXT_DIM, TEXT_MAIN, FONT

## Key Callback IDs (must not break)
- `tick` — 2s interval driving `_refresh` (callbacks/live.py)
- `analytics-tick` — 30s interval driving `_analytics_refresh` (callbacks/analytics.py)
- `agents-tick` — 60s interval driving `_agents_refresh` (callbacks/agents.py)
- `card-tech-hdr`, `card-analyst-hdr`, `card-risk-hdr`, `card-macro-hdr` — agent card headers
- `card-tech-body`, `card-analyst-body`, `card-risk-body`, `card-macro-body` — agent card bodies
- `card-arb` — arbitration card
- `sec-agent-cards` — agent panel wrapper (style output)
- `live-track-records` — track record badges in LIVE tab (children output, 24th in _refresh tuple)
- `{"type": "reasoning-toggle", "index": MATCH}` — expand/collapse per agent card
- `{"type": "reasoning-collapse", "index": MATCH}` — dcc.Collapse per agent card
- Indexes: "tech", "analyst", "risk", "macro"
- `analytics-content`, `btn-analytics-refresh`
- `bt-results`, `btn-backtest-run`, `backtest-symbol`, `backtest-period`, `backtest-strategy`
- `lb-results`, `btn-lb-run`, `lb-scenario`
- `heatmap-content`, `heatmap-updated`, `btn-heatmap-refresh`
- `agents-content`, `btn-agents-refresh`

## Tabs (7 total)
1. LIVE (`value="live"`)
2. ANALYTICS (`value="analytics"`)
3. BACKTEST (`value="backtest"`)
4. LEADERBOARD (`value="leaderboard"`)
5. HEATMAP (`value="heatmap"`) — two go.Heatmap charts, button-refresh only
6. AGENTS (`value="agents"`) — agent performance table + postmortems, 60s auto-refresh
7. TERMINAL (`value="terminal"`) — watchlist, news, screener, alerts, compare

## DB Helpers (in dashboard/layout.py)
- `_load_trades_db()` — trades table (500 rows)
- `_load_agent_memory()` — agent_memory table (1000 rows)
- `_load_postmortem()` — postmortem table (100 rows)

## _refresh callback tuple (24 outputs, in order)
page_style, topbar_style, dot_cls, round_num, pause_cls,
sec_portfolio, sec_emotion, sec_graph, sec_stats, sec_positions,
chart_vals, fig, log_items,
hdr_tech, hdr_anlst, hdr_risk, hdr_macro,
body_tech, body_anlst, body_risk, body_macro,
card_arb, cards_style, live_track

## Patterns
- `suppress_callback_exceptions=True` — tab content IDs are NOT in static layout
- Agent cards panel only shown when `AGENT_GRAPH == "multi"` — controlled via style Output
- `live-track-records` only populated when `is_multi=True`, else returns `html.Div()`
- All inline styles — no assets/ directory, no dbc
- dcc.Collapse wraps each card body; toggle button uses MATCH pattern-matching callback
- Tab layout functions (_tab_live, _tab_analytics, etc.) return html.Div with shell IDs filled by callbacks
- Heatmap win heuristic: pair SELL to most recent BUY for same symbol before that sell timestamp
- Backtest uses `from core.backtest import run_backtest` (NOT a top-level backtest.py)
- Pre-commit hooks: ruff + black — code gets auto-fixed on commit (re-stage and re-commit if hooks fail)

## Backtest + Leaderboard
- `core/backtest.py`: `run_backtest(symbol, period, strategy)` — GBM+RSI, no LLM
- `leaderboard.py`: `Leaderboard().run_all(scenario)` — 4 configs

## Validation
- `uv run python -c "from dashboard import create_app; print('OK')"` — fast import check
- `uv run python tests/test_smoke.py` — 9/9 smoke tests
- `timeout 6 uv run python main.py` — startup check (expect "Dash is running on...")
