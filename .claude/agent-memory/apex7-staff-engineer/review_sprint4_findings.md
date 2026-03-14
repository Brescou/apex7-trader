---
name: Sprint 4 Review Findings
description: Key architectural findings from Sprint 4 review — stop-loss location, save_state atomicity, backtest API coupling
type: project
---

Sprint 4 review completed 2026-03-14. Key findings:

1. **Stop-loss is in execute_node (agent.py:828-839), not a separate graph node.** Both simple and multi graphs share this via `make_execute_node`. Do NOT create a separate stoploss_guard node — it would duplicate enforcement.

2. **save_state() exists but is not atomic** — `data.py:129-138` does raw `path.write_text()`. Approved plan to make it atomic (.tmp + rename).

3. **backtest.py return schema is a coupling point** — `leaderboard.py` and `app.py` both depend on keys: `return_pct`, `sharpe`, `max_drawdown`, `survived`, `portfolio_history`, `trades_count`, `win_rate`, `trade_log`. Any schema change must update all three files atomically.

4. **_classify() is already gone** — only `_classify_v2()` exists in app.py. CLAUDE.md pitfall about `buy()` returning `None` is outdated — it returns `{"success": False, ...}` on duplicate position.

5. **Analytics win_rate in app.py:2122-2138 is already correct** — uses real BUY/SELL matching from trades.db.

6. **.gitignore missing** entries for `.apex7_state.json` and `portfolio_state.json`.

**Why:** These findings prevent duplicate work, regressions, and cross-agent conflicts.
**How to apply:** Reference in future reviews when agents propose changes to execute_node, backtest.py, or data.py persistence.
