"""Tests for the RESET button's portfolio_state.json durability.

Covers the Review Finding: clicking RESET creates a fresh in-memory
Portfolio() (cash back to INITIAL_BALANCE) but never called save_state() —
only buy()/sell() do. portfolio_state.json kept the dead portfolio's
cash/positions until the new portfolio's first trade. A process restart
before that first trade would reload the pre-reset (dead) state and
immediately re-kill it via check_death(), silently undoing the reset.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import INITIAL_BALANCE  # noqa: E402
from core.data import Portfolio  # noqa: E402


def test_reset_persists_fresh_state_to_disk(tmp_path, monkeypatch):
    import dashboard.callbacks.live as live_mod
    from dashboard.controller import _controller_lock, _ctrl, _state

    state_path = tmp_path / "portfolio_state.json"
    monkeypatch.setattr("core.data.PORTFOLIO_STATE_PATH", str(state_path))
    monkeypatch.setattr("config.PORTFOLIO_SAVE_ENABLED", True)

    # Simulate a dead portfolio that had already saved its (near-zero) state.
    dead = Portfolio()
    dead.cash = 42.0
    dead.is_dead = True
    dead.save_state(str(state_path))
    assert json.loads(state_path.read_text())["cash"] == 42.0

    with _controller_lock:
        _state["portfolio"] = dead
        saved_ctrl_paused = _ctrl.get("paused")

    fake_ctx = MagicMock(triggered_id="btn-reset")
    try:
        with patch.object(live_mod, "ctx", fake_ctx):
            with patch.object(live_mod, "_launch", return_value=MagicMock()):
                live_mod._controls(None, None, 1, {"paused": False})
    finally:
        with _controller_lock:
            _ctrl["paused"] = saved_ctrl_paused

    # portfolio_state.json must reflect the fresh $INITIAL_BALANCE state
    # immediately — not the dead portfolio's $42, and not "file unchanged
    # until the first trade".
    on_disk = json.loads(state_path.read_text())
    assert on_disk["cash"] == float(INITIAL_BALANCE)
