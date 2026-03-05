"""Graph registry — maps graph IDs to builders."""

from data import Portfolio

GRAPHS: dict[str, dict] = {
    "simple": {
        "label":       "SIMPLE — Single LLM",
        "description": "1 agent analyse tout le contexte. Rapide, efficace.",
        "cost":        "Low",
        "latency":     "~15s/cycle",
        "color":       "#3b82f6",
    },
    "multi": {
        "label":       "MULTI-AGENT — 4 Specialists",
        "description": "Technician + Analyst + Risk Manager + Macro Watcher.",
        "cost":        "High",
        "latency":     "~45s/cycle",
        "color":       "#8b5cf6",
    },
}


def get_graph(graph_id: str, portfolio: Portfolio):
    if graph_id == "multi":
        from agent_multi import build_multi_graph
        return build_multi_graph(portfolio)
    from agent import build_graph
    return build_graph(portfolio)


def get_graph_info(graph_id: str) -> dict:
    return GRAPHS.get(graph_id, GRAPHS["simple"])
