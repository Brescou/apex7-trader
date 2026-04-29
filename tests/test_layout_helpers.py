"""Tests for pure layout / registry helpers (fast, no HTTP)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from config import INITIAL_BALANCE
from core.data import Portfolio
from core.registry import get_graph, get_graph_info
from dashboard.layout.classify import _classify_v2
from dashboard.layout.emotions import _cycle, _emotion, _thinking


def test_registry_graph_info_and_fallback() -> None:
    """Unknown graph id falls back to simple metadata."""
    multi = get_graph_info("multi")
    assert "MULTI" in multi["label"]
    assert get_graph_info("definitely_unknown") == get_graph_info("simple")


def test_registry_get_graph_builds() -> None:
    """Both graph builders return a compiled graph object."""
    p = Portfolio()
    g1 = get_graph("simple", p)
    g2 = get_graph("multi", p)
    assert g1 is not None and g2 is not None


@pytest.mark.parametrize(
    "msg,level,expected_badge",
    [
        ("x", "critical", "DEATH"),
        ("x", "error", "ERR"),
        ("x", "warning", "WARN"),
        ("BUY AAPL", "info", "BUY"),
        ("SELL AAPL +5", "info", "SELL WIN"),
        ("SELL AAPL", "info", "SELL LOSS"),
        ("HOLD ok", "info", "HOLD"),
        ("Skip risk", "info", "SKIP"),
        ("Anthropic timeout", "info", "AI"),
        ("did web search today", "info", "AI"),
        ("Analysis: rsi low", "info", "INTEL"),
        ("[SIM][TECH] vote", "info", "TECH"),
        ("technician: rsi", "info", "TECH"),
        ("[SIM][ANLST] ok", "info", "ANLST"),
        ("analyst: news", "info", "ANLST"),
        ("[SIM][RISK] hi", "info", "RISK"),
        ("risk_manager: var", "info", "RISK"),
        ("[SIM][MACRO] fed", "info", "MACRO"),
        ("macro_watcher: vix", "info", "MACRO"),
        ("supervisor: brief", "info", "SUPV"),
        ("arbitrate: merged", "info", "ARBIT"),
        ("[SIM] tick", "info", "SIM"),
        ("=== CYCLE 1 START ===", "info", "CYC"),
        ("Fetching data", "info", "MKT"),
        ("Prices updated", "info", "MKT"),
        ("random log line", "info", "LOG"),
    ],
)
def test_classify_v2_badge(msg: str, level: str, expected_badge: str) -> None:
    """Log lines map to the expected classification badge."""
    badge, _color = _classify_v2(msg, level)
    assert badge == expected_badge


def test_emotion_value_bands() -> None:
    """Portfolio value / balance ratio maps to emotion labels."""
    ib = float(INITIAL_BALANCE)
    assert _emotion(ib * 1.6) == "EUPHORIC"
    assert _emotion(ib * 1.2) == "EXCITED"
    assert _emotion(ib * 1.0) == "FOCUSED"
    assert _emotion(ib * 0.8) == "CALM"
    assert _emotion(ib * 0.6) == "NERVOUS"
    assert _emotion(ib * 0.2) == "PANIC"
    assert _emotion(ib * 0.19) == "DESPERATE"


def test_cycle_parses_from_agent_log() -> None:
    """Round number is read from the latest CYCLE line in the agent log."""
    p = Portfolio()
    p.agent_log.append({"message": "noise", "level": "info"})
    p.agent_log.append({"message": "=== CYCLE 7 START ===", "level": "info"})
    assert _cycle(p) == 7


def test_thinking_reflects_controller_state() -> None:
    """``_thinking`` mirrors ``_state['thinking']`` (used by status dot)."""
    from dashboard.controller import _controller_lock, _state

    p = Portfolio()
    prev = _state.get("thinking", False)
    try:
        with _controller_lock:
            _state["thinking"] = True
        assert _thinking(p) is True
        with _controller_lock:
            _state["thinking"] = False
        assert _thinking(p) is False
    finally:
        with _controller_lock:
            _state["thinking"] = prev
