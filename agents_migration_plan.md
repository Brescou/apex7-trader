# agents/ Migration Plan — Task #3

## Objective
Migrate `agent.py` and `agent_multi.py` into an `agents/` package while keeping all existing callers working and all 9/9 smoke tests passing.

---

## Order of Operations (Steps A through K)

### Step A: Create `agents/shared/state.py`
Extract from `agent.py`:
- `AgentState` TypedDict (all fields unchanged)

Extract from `agent_multi.py`:
- `MultiAgentState` TypedDict (all fields unchanged)

Imports needed: `typing`, `operator`, `Annotated`, `TypedDict`, `List`, `Optional`

No dependencies on other new modules — safe to create first.

**Validate:** `uv run python -c "from agents.shared.state import AgentState, MultiAgentState; print('OK')"`

---

### Step B: Create `agents/shared/nodes.py`
Extract from `agent.py`:
- `_ts()`, `_entry()`, `_parse_json_obj()` helpers
- `_llm()` agentic web-search loop
- `_sim_mode` dict, `set_simulation_mode()`, `get_simulation_mode()`
- `_prev_prices`, `_fetch_prices_sync()`, `_fetch_news_sync()`, `_fetch_sentiment_sync()`, `_gather_data()`, `_run_async()`, `_is_flat()`, `_portfolio_value()`
- All simulation engine globals and functions: `_SIM_NEWS_TEMPLATES`, `_SIM_THOUGHTS`, `_sim_price_history`, `_sim_rsi()`, `_sim_step_prices()`, `_sim_seed_prices()`, `sim_fetch_data()`, `sim_analyze()`, `sim_research()`
- `_write_env_var()`, `set_simulation_mode()`, `get_simulation_mode()`
- All graph nodes: `load_memory_node`, `make_fetch_data_node()`, `analyze_node`, `research_node`, `risk_check_node`, `make_execute_node()`, `make_save_memory_node()`, `skip_node`
- Routing helpers: `_route_analyze()`, `_route_risk()`
- DB constants: `DB_PATH`, `_SCHEMA`, `_init_db()`
- Model constants: `SONNET_ID`, `HAIKU_ID`, `sonnet`, `haiku`
- `_agent_status`, `get_agent_status()`

Imports: `agents.shared.state`, `config`, `core.data`

**Potential circular import risk:** `nodes.py` imports `AgentState` from `agents.shared.state`. `state.py` imports nothing from `nodes.py`. No circular dependency.

**Validate:** `uv run python -c "from agents.shared.nodes import load_memory_node, execute_node; print('OK')"`

Note: `execute_node` is created by `make_execute_node()` — the validate command will need a portfolio instance. Use instead:
`uv run python -c "from agents.shared.nodes import load_memory_node, make_execute_node; print('OK')"`

---

### Step C: Create `agents/simple.py`
Contents = what remains of `agent.py` after shared elements are extracted:
- `build_graph(portfolio)` — imports nodes/state from `agents.shared`
- `start_agent(portfolio)` — the standalone thread entry point
- The `if __name__ == "__main__"` standalone test block
- Module-level `agent_graph = build_graph(_Portfolio())` for LangGraph Studio

Imports from: `agents.shared.nodes`, `agents.shared.state`, `config`, `core.data`

**No circular imports:** `simple.py` only imports from `shared/` — no back-references.

**Validate:** `uv run python -c "from agents.simple import build_graph; from core.data import Portfolio; g = build_graph(Portfolio()); print('OK')"`

---

### Step D: Create `agents/multi.py`
Contents = what remains of `agent_multi.py` after shared elements are removed:
- `WEIGHTS`, `_cached_weights`, `_weights_computed_at`, `_compute_dynamic_weights()`
- Simulation helpers: `sim_technician()`, `sim_analyst()`, `sim_risk_manager()`, `sim_macro_watcher()`
- Live specialist nodes: `supervisor_node()`, `technician_node()`, `analyst_node()`, `risk_manager_node()`, `macro_watcher_node()`
- `arbitrate_node()`
- `run_daily_postmortem()`
- Routing: `_route_arbitrate()`, `_route_to_agents()`
- `build_multi_graph(portfolio)`
- `build_graph = build_multi_graph` alias (for test compatibility)
- Module-level `agent_multi_graph = build_multi_graph(_Portfolio())` for LangGraph Studio

Imports from: `agents.shared.nodes`, `agents.shared.state`, `config`, `core.data`

**No circular imports:** `multi.py` only imports from `shared/` — no back-references.

**Validate:** `uv run python -c "from agents.multi import build_multi_graph; from core.data import Portfolio; g = build_multi_graph(Portfolio()); print('OK')"`

---

### Step E: Create `agents/__init__.py`
```python
from agents.simple import build_graph as build_simple_graph
from agents.multi import build_multi_graph
__all__ = ["build_simple_graph", "build_multi_graph"]
```

**Validate:** `uv run python -c "from agents import build_simple_graph, build_multi_graph; print('OK')"`

---

### Step F: Create `agents/shared/__init__.py`
Empty file (marks package).

---

### Step G: Update `core/registry.py`
Change lazy imports:
- `from agent_multi import build_multi_graph` → `from agents.multi import build_multi_graph`
- `from agent import build_graph` → `from agents.simple import build_graph`

**Validate:** `uv run python -c "from core.registry import get_graph; print('OK')"`

---

### Step H: Update `main.py`
`main.py` only imports `from app import app` — no direct agent imports. No changes needed.

Check `app.py` for agent imports that might reference `agent.py` or `agent_multi.py` directly. If found, update those imports to `agents.simple` / `agents.multi`.

---

### Step I: Update `langgraph.json`
Current paths:
```json
"apex7_simple": "./agent.py:agent_graph"
"apex7_multi":  "./agent_multi.py:agent_multi_graph"
```

Update to:
```json
"apex7_simple": "./agents/simple.py:agent_graph"
"apex7_multi":  "./agents/multi.py:agent_multi_graph"
```

---

### Step J: Run smoke tests — must be 9/9
`uv run python tests/test_smoke.py`

The smoke test file imports:
- `from agent import build_graph as build_simple_graph` (test_simple_graph_build)
- `from agent_multi import build_multi_graph` (test_multi_graph_build)
- `from agent import build_graph as build_simple_graph, _sim_mode` (test_simulation_cycle)

**These tests reference `agent` and `agent_multi` by old module names.** Since the plan requires deleting `agent.py` and `agent_multi.py`, we need to update the smoke tests to use the new import paths, OR keep thin compatibility shims in `agent.py`/`agent_multi.py` that re-export from the `agents/` package until Step K.

**Decision:** Update `tests/test_smoke.py` import paths in Step J before running tests:
- `from agent import build_graph` → `from agents.simple import build_graph`
- `from agent_multi import build_multi_graph` → `from agents.multi import build_multi_graph`
- `from agent import build_graph, _sim_mode` → `from agents.simple import build_graph; from agents.shared.nodes import _sim_mode`

---

### Step K: Delete originals — only after 9/9
```bash
git rm agent.py agent_multi.py
```

---

## Circular Import Analysis

The key concern is between `nodes.py` and `simple.py` / `multi.py`:

```
agents/shared/state.py   ← no imports from agents/
agents/shared/nodes.py   ← imports from agents.shared.state, config, core.data
agents/simple.py         ← imports from agents.shared.nodes, agents.shared.state
agents/multi.py          ← imports from agents.shared.nodes, agents.shared.state
agents/__init__.py       ← imports from agents.simple, agents.multi
```

**No cycles exist.** The dependency graph is a strict DAG:
`__init__` → `simple`/`multi` → `shared/nodes` → `shared/state`

The only risk was if `shared/nodes.py` tried to import from `simple.py` or `multi.py`, but it doesn't — all shared nodes are self-contained.

---

## Import Changes Summary

| File | Old import | New import |
|------|-----------|------------|
| `core/registry.py` | `from agent import build_graph` | `from agents.simple import build_graph` |
| `core/registry.py` | `from agent_multi import build_multi_graph` | `from agents.multi import build_multi_graph` |
| `tests/test_smoke.py` | `from agent import build_graph` | `from agents.simple import build_graph` |
| `tests/test_smoke.py` | `from agent_multi import build_multi_graph` | `from agents.multi import build_multi_graph` |
| `tests/test_smoke.py` | `from agent import ..., _sim_mode` | `from agents.shared.nodes import _sim_mode` |
| `app.py` | any `from agent import ...` | `from agents.simple import ...` or `from agents.shared.nodes import ...` |
