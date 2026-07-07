"""APEX-7 — Portfolio REST routes.

Handlers are plain ``def`` (not ``async def``): they can block briefly on
``portfolio._lock`` (held by the agent loop during a live cycle) or on
SQLite retries in ``_db_read``. FastAPI runs sync handlers in a threadpool,
keeping the event loop / WebSocket broadcaster responsive.
"""

from fastapi import APIRouter, HTTPException

from api.serializers import serialize_state

router = APIRouter()


@router.get("/portfolio")
def get_portfolio():
    from agents.shared.nodes import get_runtime_mode
    from dashboard.controller import _controller_lock, _ctrl, _state

    with _controller_lock:
        portfolio = _state.get("portfolio")
        cycle = _ctrl.get("cycle", 0)
        thinking = _state.get("thinking", False)
        votes = list(_state.get("last_votes", []))
        arb = dict(_state.get("last_arb", {}))
        consecutive_holds = _state.get("consecutive_holds", 0)
    # Read live, not the cycle-cached _ctrl["mode"] — see broadcaster.py.
    mode = get_runtime_mode()

    if portfolio is None:
        raise HTTPException(503, "Controller not started")

    return serialize_state(
        portfolio=portfolio,
        cycle=cycle,
        thinking=thinking,
        mode=mode,
        votes=votes,
        arb=arb,
        consecutive_holds=consecutive_holds,
    )


@router.get("/trades")
def get_trades():
    from dashboard.controller import _controller_lock, _state

    with _controller_lock:
        portfolio = _state.get("portfolio")

    if portfolio is None:
        raise HTTPException(503, "Controller not started")

    with portfolio._lock:
        history = list(portfolio.trade_history)

    return {"trades": list(reversed(history))}


@router.get("/analytics")
def get_analytics():
    """Compute stats + agent accuracy from DB."""
    from agents.shared.db import _db_read

    try:
        pm_rows = _db_read(
            "SELECT symbol, buy_price, sell_price, pnl_pct, holding_hours, summary "
            "FROM postmortem ORDER BY id DESC LIMIT 20"
        )
    except Exception:
        pm_rows = []

    try:
        agent_rows = _db_read(
            "SELECT agent_name, COUNT(*) as total, "
            "SUM(CASE WHEN was_correct=1 THEN 1 ELSE 0 END) as correct "
            "FROM agent_memory WHERE was_correct IS NOT NULL "
            "GROUP BY agent_name"
        )
    except Exception:
        agent_rows = []

    postmortems = [
        {
            "sym": r[0],
            "entryPrice": round(float(r[1] or 0), 2),
            "exitPrice": round(float(r[2] or 0), 2),
            "pnlPct": round(float(r[3] or 0), 2),
            "holdDays": round(float(r[4] or 0) / 24, 1),  # holding_hours → days
            "lesson": str(r[5] or ""),
        }
        for r in (pm_rows or [])
    ]

    agent_accuracy = []
    for row in agent_rows or []:
        role, total, correct = str(row[0] or ""), int(row[1] or 0), int(row[2] or 0)
        acc = (correct / total * 100) if total else 0
        agent_accuracy.append(
            {
                "role": role,
                "total": total,
                "correct": correct,
                "accuracy": round(acc, 1),
                "validated": total >= 5,
            }
        )

    return {
        "postmortems": postmortems,
        "agentAccuracy": agent_accuracy,
    }
