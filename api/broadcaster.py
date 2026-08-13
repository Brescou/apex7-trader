"""APEX-7 — WebSocket connection manager + state broadcaster.

Polls runtime.controller._state every 500 ms and pushes JSON events
to all connected WebSocket clients. Non-invasive — zero changes to agents.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from api.serializers import serialize_state

logger = logging.getLogger("apex7.broadcaster")

# A single stalled client (e.g. a laptop that went to sleep with the TCP
# connection still technically open) must not freeze delivery to every
# other connected client — broadcast() sends concurrently and each send is
# capped at this timeout instead of awaiting one client fully before
# starting the next.
_SEND_TIMEOUT_SEC = 5.0


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info("WS client connected (%d total)", len(self.active))

    def disconnect(self, ws: WebSocket):
        self.active = [c for c in self.active if c is not ws]
        logger.info("WS client disconnected (%d remaining)", len(self.active))

    async def broadcast(self, message: dict[str, Any]):
        data = json.dumps(message)
        clients = list(self.active)
        if not clients:
            return

        async def _send(ws: WebSocket) -> WebSocket | None:
            try:
                await asyncio.wait_for(ws.send_text(data), timeout=_SEND_TIMEOUT_SEC)
                return None
            except Exception:
                return ws

        results = await asyncio.gather(*(_send(ws) for ws in clients))
        for ws in results:
            if ws is not None:
                self.disconnect(ws)

    async def send_personal(self, ws: WebSocket, message: dict[str, Any]):
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            self.disconnect(ws)


broadcaster = ConnectionManager()


async def poll_and_broadcast():
    """Background task: serialize current state and broadcast to all WS clients."""
    from agents.shared.nodes import get_runtime_mode
    from runtime.controller import _controller_lock, _ctrl, _state

    prev_cycle = -1

    while True:
        await asyncio.sleep(0.5)

        if not broadcaster.active:
            continue

        try:
            with _controller_lock:
                portfolio = _state.get("portfolio")
                cycle = _ctrl.get("cycle", 0)
                thinking = _state.get("thinking", False)
                votes = list(_state.get("last_votes", []))
                arb = dict(_state.get("last_arb", {}))
                consecutive_holds = _state.get("consecutive_holds", 0)
            # Read live, not _ctrl["mode"] — that's only refreshed once per
            # agent cycle, so a mode switch via POST /api/control/mode would
            # otherwise not show up until the next cycle starts (or never,
            # while paused/dead).
            mode = get_runtime_mode()

            if portfolio is None:
                continue

            # Always send a snapshot; clients deduplicate.
            snapshot = serialize_state(
                portfolio=portfolio,
                cycle=cycle,
                thinking=thinking,
                mode=mode,
                votes=votes,
                arb=arb,
                consecutive_holds=consecutive_holds,
            )
            await broadcaster.broadcast({"type": "snapshot", "data": snapshot})

            # Send agent votes only when cycle changes.
            if cycle != prev_cycle and votes:
                await broadcaster.broadcast(
                    {
                        "type": "agent_votes",
                        "data": {
                            "cycle": cycle,
                            "votes": votes,
                            "arbitration": arb,
                        },
                    }
                )
                prev_cycle = cycle

        except Exception as e:
            logger.warning("Broadcaster error: %s", e)
