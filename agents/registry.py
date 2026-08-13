"""agents.registry — single multi-agent graph builder + UI metadata.

Lives in ``agents/`` (not ``core/``) because it imports ``agents.multi`` and
``core/`` must never depend on ``agents/``.
"""

from agents.multi import build_multi_graph
from core.data import Portfolio

GRAPH_INFO: dict = {
    "label": "MULTI-AGENT — 6 Specialists",
    "description": (
        "Technician + Analyst + Risk Manager + Macro Watcher " "+ Economist + Geopolitician."
    ),
    "cost": "High",
    "latency": "~90s/cycle",
    "color": "#8b5cf6",
}


def get_graph(portfolio: Portfolio):
    """Return the compiled multi-agent graph (only graph supported)."""
    return build_multi_graph(portfolio)


def get_graph_info() -> dict:
    """Return UI metadata for the active graph."""
    return GRAPH_INFO
