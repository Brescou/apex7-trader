"""APEX-7 — FastAPI backend for the React terminal UI.

Run with:  uvicorn api.main:app --reload --port 8000

The React frontend (Vite, port 5173) connects to:
  - REST  → http://localhost:8000/api/*
  - WS    → ws://localhost:8000/ws

This module is intentionally non-invasive: it reads _state/_ctrl from
dashboard.controller and broadcasts diffs via WebSocket. Zero changes to
agents/, core/, or market_data/.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.auth import require_auth
from api.broadcaster import poll_and_broadcast
from api.routes.control import router as control_router
from api.routes.market import router as market_router
from api.routes.portfolio import router as portfolio_router
from api.routes.ws import router as ws_router

logger = logging.getLogger("apex7.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Imported here (not at module level) so tests can patch
    # dashboard.controller.start_controller — an unqualified call to a
    # name bound at module-import time wouldn't pick up the patch.
    from dashboard.controller import start_controller

    # Safety: never auto-start in LIVE (burns Anthropic credits). Force SIM at
    # boot; the user can switch to PAPER/LIVE from the topbar once running.
    from agents.shared.nodes import get_runtime_mode, set_simulation_mode

    set_simulation_mode(True)
    logger.info("Boot mode forced to SIM (was avoiding accidental LIVE).")

    # Start the agent + postmortem threads (idempotent).
    start_controller()
    logger.info("Controller started in %s mode.", get_runtime_mode().upper())

    # Background task: poll _state every 500ms, push diffs over WebSocket.
    task = asyncio.create_task(poll_and_broadcast())
    logger.info("WebSocket broadcaster started.")

    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="APEX-7 API",
    version="3.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_auth_dep = [Depends(require_auth)]
app.include_router(portfolio_router, prefix="/api", dependencies=_auth_dep)
app.include_router(market_router, prefix="/api/market", dependencies=_auth_dep)
app.include_router(control_router, prefix="/api/control", dependencies=_auth_dep)
app.include_router(ws_router)  # WebSocket auth is handled inside the route (see api/auth.py)


@app.get("/health")
def health():
    from agents.shared.nodes import get_runtime_mode
    from dashboard.controller import _controller_lock, _ctrl, _state

    with _controller_lock:
        portfolio = _state.get("portfolio")
        cycle = _ctrl.get("cycle", 0)
    mode = get_runtime_mode()
    alive = not portfolio.is_dead if portfolio else False
    body = {
        "status": "ok" if alive else "dead",
        "agent_alive": alive,
        "cycle": cycle,
        "mode": mode,
    }
    # A dead or missing portfolio must fail the HTTP status too, not just
    # the JSON ``status`` field — otherwise ``curl -f`` never notices.
    return JSONResponse(content=body, status_code=200 if alive else 503)
