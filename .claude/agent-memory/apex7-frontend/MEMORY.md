# apex7-frontend Agent Memory

## Project Layout
- Entry: `main.py` → `app.run()`
- Dashboard: `app.py` (Dash layout + callbacks + `_agent_loop` thread)
- Agent state: `_state` dict in `app.py` — `last_votes`, `last_arb`, `portfolio`, `graph_id`
- Design tokens defined at top of `app.py`: BG_DEEP, BG_CARD, GREEN, RED, BLUE, ORANGE, GRAY, BORDER, TEXT_DIM, TEXT_MAIN, FONT
- PURPLE = "#8b5cf6" also defined in app.py

## Key Callback IDs (must not break)
- `tick` — 2s interval driving `_refresh`
- `analytics-tick` — 30s interval driving `_analytics_refresh`
- `agents-tick` — 60s interval driving `_agents_refresh`
- `card-tech-hdr`, `card-analyst-hdr`, `card-risk-hdr`, `card-macro-hdr` — agent card headers
- `card-tech-body`, `card-analyst-body`, `card-risk-body`, `card-macro-body` — agent card bodies
- `card-arb` — arbitration card
- `sec-agent-cards` — agent panel wrapper (style output)
- `live-track-records` — track record badges in LIVE tab (children output, 24th in _refresh tuple)
- `{"type": "reasoning-toggle", "index": MATCH}` — expand/collapse per agent card
- `{"type": "reasoning-collapse", "index": MATCH}` — dcc.Collapse per agent card
- Indexes: "tech", "analyst", "risk", "macro"
- `analytics-content`, `btn-analytics-refresh`
- `bt-results`, `btn-backtest-run`, `bt-scenario`, `bt-config`
- `lb-results`, `btn-lb-run`, `lb-scenario`
- `heatmap-content`, `heatmap-updated`, `btn-heatmap-refresh`
- `agents-content`, `btn-agents-refresh`

## Tabs (6 total)
1. LIVE (`value="live"`)
2. ANALYTICS (`value="analytics"`)
3. BACKTEST (`value="backtest"`)
4. LEADERBOARD (`value="leaderboard"`)
5. HEATMAP (`value="heatmap"`) — two go.Heatmap charts, button-refresh only
6. AGENTS (`value="agents"`) — agent performance table + postmortems, 60s auto-refresh

## DB Helpers
- `_load_trades_db()` — trades table (500 rows)
- `_load_agent_memory()` — agent_memory table (1000 rows): id, timestamp, agent_name, symbol, vote, confidence, was_correct, lesson, source
- `_load_postmortem()` — postmortem table (100 rows): id, timestamp, symbol, buy_price, sell_price, pnl_pct, holding_hours, agents_correct, summary, source

## _refresh callback tuple (24 outputs, in order)
page_style, topbar_style, dot_cls, round_num, pause_cls,
sec_portfolio, sec_emotion, sec_graph, sec_stats, sec_positions,
chart_vals, fig, log_items,
hdr_tech, hdr_anlst, hdr_risk, hdr_macro,
body_tech, body_anlst, body_risk, body_macro,
card_arb, cards_style, live_track

## Patterns
- `suppress_callback_exceptions=True` — tab content IDs are NOT in static layout, only in tab layout functions
- Agent cards panel only shown when `AGENT_GRAPH == "multi"` — controlled via style Output
- `live-track-records` only populated when `is_multi=True`, else returns `html.Div()`
- All inline styles — no assets/ directory, no dbc
- dcc.Collapse wraps each card body; toggle button uses MATCH pattern-matching callback
- Tab layout functions (_tab_live, _tab_analytics, etc.) return html.Div with shell IDs filled by callbacks
- Heatmap win heuristic: pair SELL to most recent BUY for same symbol before that sell timestamp

## Backtest + Leaderboard
- `backtest.py`: `BacktestEngine(scenario, config)` — GBM+RSI, no agent.py state, no LLM
  - Scenarios: "Bull Market", "Bear Market", "High Volatility", "Flat Market"
  - `config` dict accepts `max_alloc_pct` to vary position sizing
  - Returns: return_pct, sharpe, max_drawdown, survived, portfolio_history, trades_count, win_rate, trade_log
  - Win_rate: pairs each SELL to most recent BUY for same symbol via `portfolio.trade_history` (key: "time")
  - DO NOT modify `_sim_mode` in agent.py from BacktestEngine — race condition with live agent thread
- `leaderboard.py`: `Leaderboard().run_all(scenario)` — 4 configs (CONSERVATIVE=15%, BALANCED=25%, AGGRESSIVE=40%, APEX-7=MAX_ALLOC_PCT), run(80) each

## Validation
- `uv run python -c "import app"` — fast syntax/import check
- `uv run python main.py` — full run at http://localhost:8050
