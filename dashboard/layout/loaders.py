"""APEX-7 — SQLite read helpers for the dashboard.

These ``_load_*`` functions read from whichever DB ``_db_read`` resolves
to (live / paper / sim), so analytics tabs follow the active runtime mode.
They are pure data loaders — no Dash/HTML imports — split out of
``helpers.py`` to keep DB access separate from the UI builders.
"""

from agents.shared.nodes import _db_read


def _load_agent_memory() -> list[dict]:
    rows = _db_read(
        "SELECT id,timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source "
        "FROM agent_memory ORDER BY timestamp DESC LIMIT 1000"
    )
    cols = (
        "id",
        "timestamp",
        "agent_name",
        "symbol",
        "vote",
        "confidence",
        "was_correct",
        "lesson",
        "source",
    )
    return [dict(zip(cols, r)) for r in rows]


def _load_postmortem() -> list[dict]:
    rows = _db_read(
        "SELECT id,timestamp,symbol,buy_price,sell_price,pnl_pct,holding_hours,"
        "agents_correct,summary,source "
        "FROM postmortem ORDER BY timestamp DESC LIMIT 100"
    )
    cols = (
        "id",
        "timestamp",
        "symbol",
        "buy_price",
        "sell_price",
        "pnl_pct",
        "holding_hours",
        "agents_correct",
        "summary",
        "source",
    )
    return [dict(zip(cols, r)) for r in rows]


def _load_prompt_version_stats() -> list[dict]:
    """Per-``prompt_version`` A/B stats from ``trades`` joined to evaluations.

    ``was_correct`` comes from the ``agent_memory`` rows sharing each trade's
    ``trace_id`` — ``evaluate_pending_trades`` writes the same verdict to every
    row of a trace, so MAX() per trace dedupes without changing the value.
    Rows are ordered by first-trade date so versions appear chronologically.
    """
    rows = _db_read(
        "SELECT COALESCE(t.prompt_version, '—') AS version, "
        "COUNT(*) AS n_trades, "
        "SUM(CASE WHEN UPPER(t.action)='BUY' THEN 1 ELSE 0 END) AS buys, "
        "SUM(CASE WHEN UPPER(t.action)='SELL' THEN 1 ELSE 0 END) AS sells, "
        "AVG(t.confidence) AS avg_confidence, "
        "SUM(CASE WHEN m.was_correct = 1 THEN 1 ELSE 0 END) AS wins, "
        "SUM(CASE WHEN m.was_correct IS NOT NULL THEN 1 ELSE 0 END) AS evaluated, "
        "MIN(t.timestamp) AS first_trade, MAX(t.timestamp) AS last_trade "
        "FROM trades t "
        "LEFT JOIN (SELECT trace_id, MAX(was_correct) AS was_correct "
        "           FROM agent_memory WHERE trace_id IS NOT NULL "
        "           GROUP BY trace_id) m ON m.trace_id = t.trace_id "
        "GROUP BY version ORDER BY MIN(t.timestamp)"
    )
    cols = (
        "version",
        "n_trades",
        "buys",
        "sells",
        "avg_confidence",
        "wins",
        "evaluated",
        "first_trade",
        "last_trade",
    )
    return [dict(zip(cols, r)) for r in rows]


def _load_trades_db() -> list[dict]:
    rows = _db_read(
        "SELECT id,timestamp,symbol,action,price,amount_usd,shares,"
        "reasoning,confidence,emotion,portfolio_value_after,lesson,trace_id,source "
        "FROM trades ORDER BY timestamp DESC LIMIT 500"
    )
    cols = (
        "id",
        "timestamp",
        "symbol",
        "action",
        "price",
        "amount_usd",
        "shares",
        "reasoning",
        "confidence",
        "emotion",
        "portfolio_value_after",
        "lesson",
        "trace_id",
        "source",
    )
    return [dict(zip(cols, r)) for r in rows]
