"""Tests for the agent graph registry (fast, no HTTP)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.registry import get_graph, get_graph_info
from core.data import Portfolio


def test_registry_graph_info() -> None:
    """``get_graph_info`` exposes UI metadata for the multi-agent graph."""
    info = get_graph_info()
    assert "MULTI" in info["label"]
    assert "6" in info["label"]
    for key in ("description", "cost", "latency", "color"):
        assert key in info
    assert "Economist" in info["description"]
    assert "Geopolitician" in info["description"]


def test_registry_get_graph_builds() -> None:
    """``get_graph`` returns a compiled multi-agent graph."""
    p = Portfolio()
    g = get_graph(p)
    assert g is not None
