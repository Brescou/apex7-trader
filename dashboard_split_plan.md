# Frontend Split Plan: app.py → dashboard/ package

## Overview

Split `app.py` (3455 lines) into a `dashboard/` package while:
- Keeping `app.py` untouched as a working fallback
- Maintaining all existing callback IDs and behavior
- Adding Terminal extensions (sparklines, price alerts, multi-symbol comparison, CSV export)

---

## Import Dependency Analysis

### Current app.py imports (must be replicated correctly)
```python
from agent import get_simulation_mode, set_simulation_mode
from agent_multi import run_daily_postmortem
from backtest import BacktestEngine
from config import AGENT_GRAPH, AGENT_INTERVAL, DEATH_THRESHOLD, INITIAL_BALANCE, POSTMORTEM_HOUR, SIMULATION_MODE, WATCHLIST
from data import Portfolio
from graph_registry import get_graph, get_graph_info
from leaderboard import Leaderboard
from market_data import fetch_macro, fetch_watchlist_prices, fetch_news, run_screener
```

**Note:** When backend-refactor is complete, these will become:
- `from agents import build_simple_graph` / `from agents.simple import get_simulation_mode, set_simulation_mode`
- `from agents.multi import run_daily_postmortem`
- `from core.data import Portfolio`
- `from core.registry import get_graph, get_graph_info`
- `from core.backtest import BacktestEngine`

For now, dashboard/ will use the **current import paths** (agent, agent_multi, data, backtest, graph_registry). After backend-refactor signals completion, a single-pass update to `dashboard/server.py` and the callback files will update the import paths.

---

## Circular Import Prevention Strategy

The dependency chain MUST flow in one direction only:
```
dashboard/server.py  (no imports from dashboard/)
       ↓
dashboard/layout.py  (imports from server.py only)
       ↓
dashboard/callbacks/*.py  (import from server.py only, NOT from layout.py)
       ↓
dashboard/__init__.py  (imports server → layout → callbacks in order)
```

**Why callbacks must NOT import from layout.py:**
- layout.py defines tab layout functions (_tab_live, etc.)
- callbacks.live.py needs _tab_live in `_render_tab` — BUT `_render_tab` is itself a callback
- Solution: `_render_tab` stays in `dashboard/callbacks/live.py` and calls tab functions
- Tab functions must be importable from callbacks — so they go in `dashboard/layout.py` and callbacks import them from there
- Wait — that creates: callbacks → layout → server (OK), server ← nothing. This is fine.

**Revised safe chain:**
```
server.py ← (no local imports)
layout.py ← imports from server.py
callbacks/*.py ← imports from server.py AND layout.py (for tab functions)
__init__.py ← imports server, layout, then callbacks
```

This is safe because `layout.py` only imports from `server.py`, not from any callback file.

---

## File-by-File Allocation

### dashboard/server.py
Contains:
- All `import` statements (dash, plotly, sqlite3, threading, etc.)
- All external project imports (agent, data, config, market_data, etc.)
- All design tokens: BG_DEEP, BG_CARD, BG_HOVER, GREEN, RED, BLUE, ORANGE, YELLOW, PURPLE, GRAY, BORDER, TEXT_DIM, TEXT_MAIN, FONT
- `DB_PATH`
- `_rgba()` helper
- `_ctrl` and `_state` dicts (shared mutable state — must be in one place)
- `Portfolio` instantiation: `_state["portfolio"] = Portfolio()`
- `_agent_loop()`, `_launch()`, `_state["thread"] = _launch(...)`
- `_postmortem_loop()` and postmortem thread start
- `app = dash.Dash(...)` with `suppress_callback_exceptions=True`
- `app.index_string = ...` (full HTML template with fonts + CSS)
- `server = app.server`

### dashboard/layout.py
Contains:
- `from dashboard.server import app, server` + all design tokens + all shared state imports
- Emotion system: `_EMOTIONS` dict, `_emotion()`, `_thinking()`, `_cycle()`
- UI helper functions: `_section_label()`, `_mini_stat()`, `_classify_v2()`, `_log_entry_card()`, `_pos_card()`, `_sparkline()` (portfolio sparkline)
- DB helpers: `_load_agent_memory()`, `_load_postmortem()`, `_load_trades_db()`
- Agent card helpers: `_conf_bar_inline()`, `_action_chip()`, `_sim_chip()`, `_card_hdr_standard()`, `_body_style()`, `_ind_cell()`
- Agent body builders: `_tech_body_children()`, `_analyst_body_children()`, `_risk_body_children()`, `_macro_body_children()`
- Arbitration card: `_arb_card_children()`, `_build_arb_card()`
- All tab layout functions: `_tab_live()`, `_tab_analytics()`, `_tab_backtest()`, `_tab_heatmap()`, `_tab_agents()`, `_tab_leaderboard()`, `_tab_terminal()`
- `app.layout = create_layout()` — the full `html.Div(...)` layout including stores, intervals, topbar, tabs bar, tab-content div
- `_fmt_volume()`, `_watchlist_row()` (used by terminal callbacks but defined here for layout access)
- Additional agent card detail helpers: `_sent_bar()`, `_macro_bar()`, `_tech_body_children()`, etc.

**`create_layout()` function** wraps `app.layout = html.Div(...)` so it can be called from `__init__.py`.

### dashboard/callbacks/live.py
Callbacks:
1. `_render_tab` — Output("tab-content", "children"), Input("main-tabs", "value")
2. `_toggle_mode` — Output("mode-store", "data"), Input("mode-radio", "value")
3. `_mode_badge` — Output("mode-badge", ...), Input("mode-store", "data")
4. `_controls` — Output("ctrl-store", "data"), Inputs(btn-pause, btn-step, btn-reset)
5. `_switch_graph` — Output("graph-store", "data"), Input("graph-selector", "value")
6. `_refresh` — the big 24-output callback, Input("tick", ...) + Input("ctrl-store", ...)
7. `_toggle_reasoning` — pattern-matching MATCH callback for reasoning cards

Imports needed: `from dashboard.server import app, _ctrl, _state`, `from dashboard.layout import ...tab functions + helper builders`

### dashboard/callbacks/analytics.py
Callbacks:
1. `_analytics_refresh` — Output("analytics-content", ...), Inputs(analytics-tick, btn-analytics-refresh)

Imports: `from dashboard.server import app, DB_PATH` + design tokens, `_load_trades_db` from layout

### dashboard/callbacks/backtest.py
Callbacks:
1. `_backtest_run` — Output("bt-results", ...), Input("btn-backtest-run", ...) + States

Imports: `from dashboard.server import app` + design tokens, `BacktestEngine` / `run_backtest`

### dashboard/callbacks/terminal.py
Existing callbacks:
1. `_update_macro_bar` — Output("macro-bar-content"), Input("macro-interval")
2. `_add_symbol` — Output("terminal-watchlist"), Input("btn-watchlist-add")
3. `_remove_symbol` — Output("terminal-watchlist" allow_duplicate), Input({"type":"watchlist-remove", "index":MATCH})
4. `_update_watchlist` — Output("watchlist-chips") + Output("watchlist-table"), multiple Inputs
5. `_select_symbol` — Output("terminal-active-symbol"), Input({"type":"watchlist-row-btn","index":MATCH})
6. `_update_news` — Output("news-feed") + Output("news-header"), multiple Inputs
7. `_run_screener` — Output("screener-results"), Input("btn-screener-run") + States

**New Terminal extension callbacks:**

8. `_update_sparkline_col` — adds sparkline charts in watchlist rows
   - Triggered by watchlist-interval or terminal-watchlist data changes
   - Calls `market_data.fetch_sparkline(symbol)` (provided by backend-terminal)
   - Output: updates each watchlist row to include a `dcc.Graph` sparkline

9. `_set_price_alert` — Output("price-alerts-store"), Input("btn-set-alert"), States(alert-symbol-input, alert-direction-dropdown, alert-price-input, "price-alerts-store")

10. `_remove_price_alert` — Output("price-alerts-store", allow_duplicate), Input({"type":"alert-remove-btn","index":MATCH})

11. `_check_alerts` — Output("alert-banner", "children") + Output("alert-count-badge", "children") + Output("price-alerts-store", allow_duplicate)
    - Input("check-alerts-interval", "n_intervals")
    - Compares current prices vs thresholds; triggers flash banner

12. `_toggle_compare_panel` — Output("compare-collapse","is_open"), Input("btn-compare","n_clicks")

13. `_update_comparison_chart` — Output("compare-chart","figure")
    - Input("compare-period","value") + State("compare-symbols","value")
    - Calls `market_data.fetch_comparison(symbols, period)`

14. `_export_csv` — Output("csv-download","data")
    - Input("btn-export-csv","n_clicks"), State("terminal-watchlist","data")
    - Uses `dcc.send_data_frame` or `dcc.send_string`

### dashboard/callbacks/history.py
No existing HISTORY tab in app.py — this file will be created as an empty stub with a comment noting it's a placeholder for future history functionality.

### dashboard/callbacks/heatmap.py
Callbacks:
1. `_heatmap_refresh` — Output("heatmap-content") + Output("heatmap-updated"), Input("btn-heatmap-refresh")
2. `_agents_refresh` — Output("agents-content"), Inputs(agents-tick, btn-agents-refresh)
3. `_lb_run` — Output("lb-results"), Input("btn-lb-run") + State("lb-scenario")

### dashboard/callbacks/__init__.py
```python
from dashboard.callbacks import live, analytics, backtest, terminal, history, heatmap
```

### dashboard/__init__.py
```python
from dashboard.server import app, server
from dashboard import layout          # registers app.layout
from dashboard.callbacks import live, analytics, backtest, terminal, history, heatmap

def create_app():
    return app

__all__ = ["app", "server", "create_app"]
```

---

## New dcc.Store and dcc.Interval IDs (Terminal extensions)

### Added to app.layout (in dashboard/layout.py `create_layout()`):
```python
dcc.Store(id="price-alerts-store", data=[]),
dcc.Interval(id="check-alerts-interval", interval=10000, n_intervals=0),
dcc.Download(id="csv-download"),
```

### Added inside `_tab_terminal()` layout (in dashboard/layout.py):
- `id="alert-banner"` — html.Div for flash display
- `id="alert-count-badge"` — span in tab label (or near watchlist header)
- `id="alert-symbol-input"` — dcc.Input for new alert symbol
- `id="alert-direction-dropdown"` — dcc.Dropdown ABOVE/BELOW
- `id="alert-price-input"` — dcc.Input for price threshold
- `id="btn-set-alert"` — html.Button
- `id={"type":"alert-remove-btn","index":sym}` — pattern-matching remove buttons
- `id="btn-compare"` — html.Button "COMPARE"
- `id="compare-collapse"` — dcc.Collapse wrapping comparison panel
- `id="compare-symbols"` — dcc.Checklist for symbol selection
- `id="compare-period"` — dcc.Dropdown 1d/5d/1mo/3mo
- `id="compare-chart"` — dcc.Graph for overlay chart
- `id="btn-export-csv"` — html.Button "CSV"

### Colors for comparison chart (GOLD not in current tokens — add to server.py):
```python
GOLD = "#f59e0b"  # same as YELLOW already defined — use YELLOW
```
Comparison palette: `[BLUE, PURPLE, GREEN, RED, ORANGE]` (all existing tokens)

---

## Critical Constraints Checklist

- [ ] All existing callback IDs preserved: `tick`, `analytics-tick`, `agents-tick`, `card-tech-hdr`, etc. (see MEMORY.md for full list)
- [ ] `suppress_callback_exceptions=True` stays in app init — tab content IDs not in static layout
- [ ] `_state` and `_ctrl` dicts defined in `server.py` and imported by `callbacks/live.py`
- [ ] `app.layout` assigned inside `create_layout()` called from `dashboard/__init__.py`
- [ ] No `assets/` directory — all CSS stays inline in `index_string` and style= props
- [ ] `app.py` NOT deleted — kept as working fallback
- [ ] `main.py` NOT modified — it calls `app.run()` from existing `app.py`

---

## Validation Command

```bash
uv run python -c "from dashboard import create_app; app = create_app(); print('PASS')"
```

---

## Implementation Order

1. Create `dashboard/` directory structure (empty `__init__.py` files)
2. Write `dashboard/server.py` — Dash init, design tokens, shared state, agent loop
3. Write `dashboard/layout.py` — all helpers, tab functions, `create_layout()`
4. Write `dashboard/callbacks/live.py` — tab routing + live tab callbacks
5. Write `dashboard/callbacks/analytics.py`
6. Write `dashboard/callbacks/backtest.py`
7. Write `dashboard/callbacks/heatmap.py` (heatmap + agents + leaderboard)
8. Write `dashboard/callbacks/terminal.py` (existing + new extensions)
9. Write `dashboard/callbacks/history.py` (stub)
10. Write `dashboard/callbacks/__init__.py`
11. Write `dashboard/__init__.py`
12. Validate: `uv run python -c "from dashboard import create_app; app = create_app(); print('PASS')"`
13. Update `main.py` (optional — only if switching entry point; otherwise keep as-is until QA)

---

## Post-backend-refactor Import Path Updates

Once backend-refactor signals "done", update only `dashboard/server.py` import block:
```python
# OLD (current)
from agent import get_simulation_mode, set_simulation_mode
from agent_multi import run_daily_postmortem
from data import Portfolio
from graph_registry import get_graph, get_graph_info
from backtest import BacktestEngine

# NEW (after backend-refactor)
from agents.simple import get_simulation_mode, set_simulation_mode
from agents.multi import run_daily_postmortem
from core.data import Portfolio
from core.registry import get_graph, get_graph_info
from core.backtest import BacktestEngine
```
All other files import from `dashboard.server` so no cascade changes needed.
