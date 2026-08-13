"""APEX-7 — Control routes: mode switch, pause/resume, watchlist.

Handlers are plain ``def`` (not ``async def``): mode/watchlist writes go
through blocking file I/O (``.env``) and SQLite. FastAPI runs sync handlers
in a threadpool, keeping the event loop / WebSocket broadcaster responsive.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ModeRequest(BaseModel):
    mode: str  # "live" | "paper" | "sim"


class WatchlistRequest(BaseModel):
    symbol: str


@router.post("/mode")
def set_mode(req: ModeRequest):
    from agents.shared.nodes import set_paper_mode, set_simulation_mode

    m = req.mode.lower()
    if m == "sim":
        set_simulation_mode(True)
    elif m == "paper":
        set_paper_mode(True)
    elif m == "live":
        set_simulation_mode(False)
        set_paper_mode(False)
    else:
        return {"ok": False, "error": f"Unknown mode: {m}"}
    return {"ok": True, "mode": m}


@router.post("/pause")
def pause():
    from runtime.controller import _controller_lock, _ctrl

    with _controller_lock:
        _ctrl["paused"] = True
    return {"ok": True, "paused": True}


@router.post("/resume")
def resume():
    from runtime.controller import _controller_lock, _ctrl

    with _controller_lock:
        _ctrl["paused"] = False
    return {"ok": True, "paused": False}


@router.get("/watchlist")
def get_watchlist():
    from agents.shared.watchlist import get_watchlist as _get

    return {"watchlist": _get()}


@router.post("/watchlist/add")
def add_to_watchlist(req: WatchlistRequest):
    from agents.shared.watchlist import add_to_watchlist

    ok = add_to_watchlist(req.symbol.upper())
    return {"ok": ok, "symbol": req.symbol.upper()}


@router.post("/watchlist/remove")
def remove_from_watchlist(req: WatchlistRequest):
    from agents.shared.watchlist import remove_from_watchlist

    ok = remove_from_watchlist(req.symbol.upper())
    return {"ok": ok, "symbol": req.symbol.upper()}
