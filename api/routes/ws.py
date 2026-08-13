"""APEX-7 — WebSocket route."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from api.auth import ws_auth_ok
from api.broadcaster import broadcaster
from api.serializers import serialize_state

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    if not ws_auth_ok(ws):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await broadcaster.connect(ws)
    try:
        # Send full snapshot immediately on connect.
        from agents.shared.nodes import get_runtime_mode
        from runtime.controller import _controller_lock, _ctrl, _state

        with _controller_lock:
            portfolio = _state.get("portfolio")
            cycle = _ctrl.get("cycle", 0)
            thinking = _state.get("thinking", False)
            votes = list(_state.get("last_votes", []))
            arb = dict(_state.get("last_arb", {}))
            consecutive_holds = _state.get("consecutive_holds", 0)
        # Read live, not the cycle-cached _ctrl["mode"] — see broadcaster.py.
        mode = get_runtime_mode()

        if portfolio:
            snapshot = serialize_state(
                portfolio=portfolio,
                cycle=cycle,
                thinking=thinking,
                mode=mode,
                votes=votes,
                arb=arb,
                consecutive_holds=consecutive_holds,
            )
            await broadcaster.send_personal(ws, {"type": "snapshot", "data": snapshot})

        # Keep connection alive; client sends pings.
        while True:
            await ws.receive_text()

    except WebSocketDisconnect:
        broadcaster.disconnect(ws)
    except Exception:
        broadcaster.disconnect(ws)
