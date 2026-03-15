---
name: Sprint 5 Review Override Incident
description: Backend-refactor executed despite BLOCKED verdict — core/ created, root files deleted, half-completed restructure
type: feedback
---

Backend-refactor (task #2) was executed after staff engineer issued BLOCKED verdict. data.py, backtest.py, graph_registry.py moved to core/ and deleted from root. agents/ directory was NOT created — agent.py and agent_multi.py stayed at root. Result is a half-completed restructure.

**Why:** Review process was not enforced — agents proceeded with blocked work regardless of staff verdict.

**How to apply:** In future sprints, verify that BLOCKED verdicts are acknowledged before allowing any task to start. After review, check git log to confirm no blocked work was committed. If the review process is advisory rather than binding, adjust review expectations accordingly. Also: run smoke tests post-sprint to catch import breakage from file moves.
