# dashboard/ Migration Plan — app.py → dashboard/ package

## Overview

Migrate `app.py` (6008 lines) into a `dashboard/` package with clear separation of concerns:
server/tokens, agent controller, layout helpers, and callbacks by tab.

---

## 1. Exact file → content mapping

### `dashboard/__init__.py` (placeholder first, final in Step F)
Final content:
```python
from dashboard.server import app, server
from dashboard import layout      # registers app.layout
from dashboard import callbacks   # triggers all @app.callback registrations

def create_app():
    return app

__all__ = ["app", "server", "create_app"]
```

### `dashboard/server.py`
Extracted from `app.py`:
- All imports: `dash`, `plotly.graph_objects`, `dcc`, `html`, `MATCH`, `DataTable`, `sqlite3`, `threading`, `time`, `datetime`, `Path`
- All config imports: `AGENT_GRAPH`, `AGENT_INTERVAL`, `DEATH_THRESHOLD`, `INITIAL_BALANCE`, `POSTMORTEM_HOUR`, `SIMULATION_MODE`, `WATCHLIST`
- All external module imports: `agent`, `agent_multi`, `core.backtest`, `core.data`, `core.registry`, `leaderboard`, `market_data`
- Design tokens: `BG_DEEP`, `BG_CARD`, `BG_HOVER`, `GREEN`, `RED`, `BLUE`, `ORANGE`, `YELLOW`, `PURPLE`, `GRAY`, `BORDER`, `TEXT_DIM`, `TEXT_MAIN`, `FONT`
- `DB_PATH`
- `_rgba()` helper
- `app = dash.Dash(...)` instantiation with `title` and `suppress_callback_exceptions=True`
- `server = app.server`
- `app.index_string = """..."""` (the full HTML template with font loading and CSS)

### `dashboard/controller.py`
Extracted from `app.py`:
- `_ctrl` dict
- `_state` dict
- `_agent_loop()` function
- `_launch()` function
- Module-level startup code: `_state["portfolio"] = Portfolio()`, `_state["thread"] = _launch(...)`
- `_last_postmortem_date` global
- `_postmortem_loop()` function
- Module-level thread start: `threading.Thread(target=_postmortem_loop, ...).start()`

Imports from `dashboard.server`: `AGENT_GRAPH`, `AGENT_INTERVAL`, all design tokens (none needed), `Portfolio`, `get_graph`, `get_simulation_mode`, `run_daily_postmortem`

### `dashboard/layout.py`
Extracted from `app.py`:
- All UI helper functions (non-callback): `_section_label()`, `_mini_stat()`, `_classify_v2()`, `_log_entry_card()`, `_pos_card()`, `_sparkline()`, `_make_sparkline_fig()`, `_load_agent_memory()`, `_load_trades_db()`, `_load_postmortem()`
- Agent card helpers: `_conf_bar_inline()`, `_action_chip()`, `_sim_chip()`, `_card_hdr_standard()`, `_body_style()`, `_ind_cell()`, `_tech_body_children()`, `_sent_bar()`, `_analyst_body_children()`, `_risk_body_children()`, `_macro_bar()`, `_macro_body_children()`, `_arb_card_children()`, `_build_arb_card()`
- Agent state helpers: `_EMOTIONS` dict, `_emotion()`, `_thinking()`, `_cycle()`
- Tab layout functions: `_tab_live()`, `_tab_analytics()`, `_tab_backtest()`, `_tab_heatmap()`, `_tab_agents()`, `_tab_leaderboard()`, `_tab_terminal()`
- Terminal helper: `_fmt_volume()`, `_watchlist_row()`
- `app.layout = html.Div(...)` assignment

Imports: `from dashboard.server import app, BG_DEEP, BG_CARD, BG_HOVER, GREEN, RED, BLUE, ORANGE, YELLOW, PURPLE, GRAY, BORDER, TEXT_DIM, TEXT_MAIN, FONT, DB_PATH, WATCHLIST, INITIAL_BALANCE, DEATH_THRESHOLD`
Also imports `from dashboard.controller import _state, _ctrl, _thinking, _cycle` (for `_thinking`, `_cycle` if needed at layout time — actually `_thinking` and `_cycle` are layout helpers, not callbacks, so they stay in `layout.py`).

Actually cleaner: `_thinking()` and `_cycle()` reference `_state` from `controller.py`, so they either go in `controller.py` (exposed via import) or import `_state` from `controller`. Simplest: keep them in `layout.py` and `from dashboard.controller import _state`.

### `dashboard/callbacks/__init__.py`
```python
from dashboard.callbacks import live, analytics, backtest_tab, leaderboard_tab, heatmap, agents, terminal
```

### `dashboard/callbacks/live.py`
Callbacks:
- `_render_tab` (tab routing, Output "tab-content")
- `_toggle_mode` (Output "mode-store")
- `_mode_badge` (Output "mode-badge")
- `_controls` (Output "ctrl-store", btn-pause/step/reset)
- `_switch_graph` (Output "graph-store")
- `_refresh` (the big 24-output callback, Input "tick")
- `_toggle_reasoning` (pattern-matching, Output reasoning-collapse/toggle)

Imports: `from dashboard.server import app` + all tokens + config; `from dashboard.controller import _state, _ctrl, _launch`; `from dashboard.layout import _tab_live, _tab_analytics, _tab_backtest, _tab_heatmap, _tab_agents, _tab_leaderboard, _tab_terminal, _log_entry_card, _sparkline, _pos_card, _section_label, _mini_stat, _emotion, _EMOTIONS, _thinking, _cycle, _card_hdr_standard, _sim_chip, _tech_body_children, _analyst_body_children, _risk_body_children, _macro_body_children, _build_arb_card, _PLACEHOLDER_HDR` (or define inline)

### `dashboard/callbacks/analytics.py`
Callbacks:
- `_analytics_refresh` (Output "analytics-content", Input "analytics-tick" + "btn-analytics-refresh")

Imports: `from dashboard.server import app` + tokens; `from dashboard.layout import _load_trades_db`

### `dashboard/callbacks/backtest_tab.py`
Callbacks:
- `_backtest_run` (Output "bt-results", Input "btn-backtest-run")

Imports: `from dashboard.server import app` + tokens + `INITIAL_BALANCE`; `from backtest import run_backtest`

### `dashboard/callbacks/leaderboard_tab.py`
Callbacks:
- `_lb_run` (Output "lb-results", Input "btn-lb-run")

Imports: `from dashboard.server import app` + tokens; `from leaderboard import Leaderboard`

### `dashboard/callbacks/heatmap.py`
Callbacks:
- `_heatmap_refresh` (Output "heatmap-content" + "heatmap-updated", Input "btn-heatmap-refresh")

Imports: `from dashboard.server import app, DB_PATH` + tokens

### `dashboard/callbacks/agents.py`
Callbacks:
- `_agents_refresh` (Output "agents-content", Input "agents-tick" + "btn-agents-refresh")

Imports: `from dashboard.server import app, DB_PATH` + tokens

### `dashboard/callbacks/terminal.py`
Callbacks (all 10 terminal callbacks):
- `_update_macro_bar`
- `_add_symbol`
- `_remove_symbol`
- `_update_watchlist`
- `_select_symbol`
- `_update_news`
- `_run_screener`
- `_toggle_compare`
- `_update_comparison`
- `_export_csv`
- `_set_alert`
- `_remove_alert`
- `_check_alerts`

Imports: `from dashboard.server import app, WATCHLIST` + tokens; `from market_data import fetch_macro, fetch_watchlist_prices, fetch_news, run_screener, fetch_sparkline, fetch_comparison`; `from dashboard.layout import _watchlist_row, _make_sparkline_fig, _fmt_volume`

---

## 2. How @app.callback registration works

All callback files import `app` from `dashboard.server` — the **same singleton instance**. The `@app.callback(...)` decorator registers each callback onto that app object at import time. The import chain is:

```
dashboard/__init__.py
  → imports dashboard.layout    (registers app.layout)
  → imports dashboard.callbacks  (triggers __init__.py)
    → imports live, analytics, backtest_tab, leaderboard_tab, heatmap, agents, terminal
      (each file does @app.callback at module level)
```

All callbacks are registered before `create_app()` returns the `app` instance.

---

## 3. Import order in dashboard/__init__.py

```python
# Step 1: server.py first — creates app, server, tokens (no circular deps)
from dashboard.server import app, server

# Step 2: controller.py — starts agent thread (imports from server + external modules)
# controller is imported by layout.py already (for _state), so it runs on layout import

# Step 3: layout.py — imports from server + controller, sets app.layout
from dashboard import layout

# Step 4: callbacks/ — each module imports app from server; registers @app.callback
from dashboard import callbacks

def create_app():
    return app
```

Note: `controller.py` is **not** imported directly in `__init__.py` — it's imported by `layout.py` (and callback files that need `_state`/`_ctrl`). This is intentional: controller must run before layout (thread starts), which runs before callbacks (uses _state).

---

## 4. Circular dependency prevention

- `server.py` imports nothing from `dashboard/`
- `controller.py` imports from `server.py` only (design tokens, app config, external modules)
- `layout.py` imports from `server.py` and `controller.py`
- `callbacks/*.py` imports from `server.py`, `controller.py`, `layout.py`
- No backward imports

---

## 5. test_smoke.py compatibility

`test_app_import` does `import app` and checks `hasattr(app, 'server') or hasattr(app, 'app')`.

After migration, we update `test_smoke.py:test_app_import` to:
```python
def test_app_import():
    from dashboard import create_app
    a = create_app()
    assert a is not None
```

OR we keep a thin `app.py` shim at root:
```python
from dashboard import app, server  # re-exports for backward compat
```

**Decision: keep a thin shim** `app.py` at root that re-exports `app` and `server`. This means `main.py` also works without changes, and `test_smoke.py` passes without modification. We only update `main.py` to import from `dashboard` (as specified in the instructions).

---

## 6. main.py update

Current `main.py`:
```python
from app import app
def main():
    app.run(debug=False, host="0.0.0.0", port=8050)
```

Updated:
```python
from dashboard import create_app
app = create_app()
def main():
    app.run(debug=False, host="0.0.0.0", port=8050)
if __name__ == "__main__":
    main()
```

---

## 7. Smoke test compatibility note

The `test_app_import` test does `import app` after migration. We will update it to:
```python
def test_app_import():
    from dashboard import create_app
    a = create_app()
    assert a is not None, "create_app() returned None"
```

All other 8 tests don't reference `app.py` directly — they will continue to pass.

---

## 8. Step-by-step implementation sequence

1. Create `dashboard/__init__.py` (empty placeholder)
2. Create `dashboard/server.py` + validate import
3. Create `dashboard/controller.py` + validate import
4. Create `dashboard/layout.py` + validate import (sets app.layout)
5. Create `dashboard/callbacks/__init__.py` + all 7 callback files + validate each
6. Finalize `dashboard/__init__.py`
7. Update `main.py`
8. Update `tests/test_smoke.py:test_app_import`
9. Run full smoke tests (9/9)
10. Run startup test (6s timeout, no traceback)
11. `git rm app.py` only after 9/9

---

## 9. Backward compat note (backtest import)

`_backtest_run` callback in app.py uses `from backtest import run_backtest` (root copy). The instructions say to use `from core.backtest import run_backtest` (canonical). I will use the canonical import.
