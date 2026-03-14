---
name: Sprint 5 Architecture Review Verdicts
description: Full import dependency map and BLOCKED/APPROVED verdicts for Sprint 5 restructuring plan
type: project
---

Sprint 5 review completed 2026-03-14. Complete import dependency map:

## Import Dependency Graph (who imports what)

**agent.py** imported by: agent_multi.py (18 symbols), app.py (2 symbols), graph_registry.py (1 fn), langgraph.json (module-level graph), tests/test_smoke.py
**agent_multi.py** imported by: app.py (1 symbol), graph_registry.py (1 fn), langgraph.json (module-level graph), tests/test_smoke.py
**data.py** imported by: agent.py, agent_multi.py, backtest.py, app.py, graph_registry.py, tests/test_smoke.py
**config.py** imported by: agent.py, agent_multi.py, data.py, backtest.py, app.py, market_data.py, leaderboard.py
**backtest.py** imported by: app.py, leaderboard.py, tests/test_smoke.py
**graph_registry.py** imported by: app.py, tests/test_smoke.py
**market_data.py** imported by: app.py
**leaderboard.py** imported by: app.py

## Critical Findings

1. **agent_multi.py imports 18 symbols from agent.py** — extracting shared nodes to agents/shared/nodes.py means BOTH agents/simple.py and agents/multi.py must import from the new location. The extraction is the riskiest part.

2. **langgraph.json uses dotted paths** (`./agent.py:agent_graph`, `./agent_multi.py:agent_multi_graph`) — must be updated to `./agents/simple.py:agent_graph` and `./agents/multi.py:agent_multi_graph`.

3. **agent.py has module-level side effects**: `_init_db()` called at import time (line 145), and `agent_graph = build_graph(_Portfolio())` at line 1187. These must remain in the new location.

4. **tests/test_smoke.py uses bare imports** (`import agent`, `import data`, etc.) — relies on sys.path manipulation. Will break after moves unless updated.

5. **CLAUDE.md/docs move**: CLAUDE.md MUST stay at project root — it's read by Claude Code automatically from the working directory. Moving it to docs/ breaks the tool.

## Verdicts

- **backend-refactor (task #2)**: BLOCKED — splitting app.py is on the hard blocklist; CLAUDE.md must stay at root; TypedDict extraction violates blocklist
- **frontend-refactor (task #3)**: BLOCKED — splitting app.py is explicitly on the hard blocklist
- **backend-terminal (task #4)**: APPROVED — market_data.py is standalone, no conflicts
- **backend-cicd (task #5)**: APPROVED with conditions — dev deps justified, no runtime dep changes

**Why:** Sprint 5 proposes high-risk file moves that touch every critical file simultaneously. The blast radius is too large for the current stage.
**How to apply:** Reference when evaluating future restructuring proposals. The safer path is incremental extraction, one module at a time, with smoke tests between each move.
