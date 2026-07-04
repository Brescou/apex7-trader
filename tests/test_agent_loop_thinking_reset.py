"""Test for dashboard/controller.py::_agent_loop's "thinking" flag reset.

Covers the Review Finding: _state["thinking"] is set True right before
graph.invoke() but was only cleared on the success path. An exception
during graph.invoke() (e.g. yfinance errors on every cycle) left
"thinking" stuck True for the whole retry sleep — the topbar's "thinking"/
"SEARCHING..." indicator stays lit continuously even though the agent is
just looping on failure, not doing any LLM work.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data import Portfolio  # noqa: E402


def test_thinking_cleared_after_graph_invoke_raises():
    import dashboard.controller as ctrl_mod

    p = Portfolio()

    def _boom(_initial_state):
        # Simulate the cycle crashing AND the portfolio being marked dead
        # so _agent_loop exits after this one cycle instead of looping.
        p.is_dead = True
        raise RuntimeError("simulated cycle failure")

    mock_graph = MagicMock()
    mock_graph.invoke.side_effect = _boom

    with patch.object(ctrl_mod, "get_graph", return_value=mock_graph):
        with patch.object(ctrl_mod, "get_simulation_mode", return_value=True):
            ctrl_mod._agent_loop(p)

    assert ctrl_mod._state["thinking"] is False
    assert ctrl_mod._state["last_error"] == "simulated cycle failure"
