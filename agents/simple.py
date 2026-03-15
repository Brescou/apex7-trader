"""
APEX-7 — Simple Agent Graph (extracted from agent.py)

Graph:
  __start__
      │
  load_memory  (haiku)
      │
  fetch_data   (async parallel — no LLM)
      │
  analyze      (sonnet + web_search)
      │
  ┌───┴───┐
  │       │
conf≥0.7  conf<0.7
  │       │
  │    research  (sonnet + web_search, max 2×)
  │       │
  └───┬───┘
      │
  risk_check   (pure Python rules)
      │
  ┌───┴───┐
  │       │
exec    skip
  │
save_memory  (haiku)
  │
__end__
"""

import threading
import time
import traceback

from langgraph.graph import END, START, StateGraph

from agents.shared.nodes import (
    _agent_status,
    _route_analyze,
    _route_risk,
    _sim_mode,
    _ts,
    analyze_node,
    load_memory_node,
    make_execute_node,
    make_fetch_data_node,
    make_save_memory_node,
    research_node,
    risk_check_node,
    skip_node,
)
from agents.shared.state import AgentState
from config import AGENT_INTERVAL, WATCHLIST
from core.data import Portfolio


def build_graph(portfolio: Portfolio | None = None):
    if portfolio is None:
        portfolio = Portfolio()
    g = StateGraph(AgentState)

    g.add_node("load_memory", load_memory_node)
    g.add_node("fetch_data", make_fetch_data_node(portfolio))
    g.add_node("analyze", analyze_node)
    g.add_node("research", research_node)
    g.add_node("risk_check", risk_check_node)
    g.add_node("execute", make_execute_node(portfolio))
    g.add_node("save_memory", make_save_memory_node(portfolio))
    g.add_node("skip", skip_node)

    g.add_edge(START, "load_memory")
    g.add_edge("load_memory", "fetch_data")
    g.add_edge("fetch_data", "analyze")

    g.add_conditional_edges(
        "analyze",
        _route_analyze,
        {"risk_check": "risk_check", "research": "research"},
    )
    g.add_edge("research", "analyze")  # loop: research feeds back into analyze

    g.add_conditional_edges(
        "risk_check",
        _route_risk,
        {"execute": "execute", "skip": "skip"},
    )
    g.add_edge("execute", "save_memory")
    g.add_edge("save_memory", END)
    g.add_edge("skip", END)

    return g.compile()


def start_agent(portfolio: Portfolio) -> threading.Thread:
    """Unused from dashboard. For standalone use only. See app.py _agent_loop."""
    graph = build_graph(portfolio)

    def _loop() -> None:
        cycle = 0
        while not portfolio.is_dead:
            cycle += 1
            portfolio.log(f"=== CYCLE {cycle} START ===")
            try:
                initial: AgentState = {
                    "balance": portfolio.cash,
                    "positions": dict(portfolio.positions),
                    "portfolio_history": [],
                    "prices": dict(portfolio.last_prices),
                    "news": "",
                    "sentiment": {},
                    "past_trades": [],
                    "known_patterns": [],
                    "round": cycle,
                    "confidence": 0.0,
                    "research_iterations": 0,
                    "decision": None,
                    "emotion": "CALM",
                    "thoughts": "",
                    "log": [],
                    "alive": True,
                    "skip_research": False,
                }
                result = graph.invoke(initial)

                _agent_status.update(
                    {
                        "cycle": cycle,
                        "emotion": result.get("emotion", "CALM"),
                        "thoughts": result.get("thoughts", ""),
                        "confidence": result.get("confidence", 0.0),
                        "decision": result.get("decision"),
                        "research_iterations": result.get("research_iterations", 0),
                        "alive": result.get("alive", True),
                        "last_update": _ts(),
                    }
                )

                # Forward structured log to portfolio (for Dash)
                for entry in result.get("log", []):
                    portfolio.log(entry["message"], entry.get("level", "info"))

                if not result.get("alive", True):
                    portfolio.is_dead = True
                    portfolio.log("DEATH CONDITION MET", "critical")
                    break

            except Exception as e:
                portfolio.log(f"Agent cycle error: {e}", "error")
                portfolio.log(traceback.format_exc(), "error")

            sleep_s = 3 if _sim_mode["enabled"] else AGENT_INTERVAL
            portfolio.log(f"=== CYCLE {cycle} DONE — sleeping {sleep_s}s ===")
            time.sleep(sleep_s)

    t = threading.Thread(target=_loop, daemon=True, name="apex7-agent")
    t.start()
    return t


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    from agents.shared.nodes import DB_PATH

    print("=" * 64)
    print("  APEX-7  AGENT v2 — Standalone Test")
    print("=" * 64)

    p = Portfolio()
    print(f"  Portfolio : ${p.cash:.2f} cash | {len(p.positions)} positions")
    print(f"  Watchlist : {WATCHLIST}")
    print(f"  DB        : {DB_PATH}")
    print()

    graph = build_graph(p)

    state: AgentState = {
        "balance": p.cash,
        "positions": {},
        "portfolio_history": [],
        "prices": {},
        "news": "",
        "sentiment": {},
        "past_trades": [],
        "known_patterns": [],
        "round": 1,
        "confidence": 0.0,
        "research_iterations": 0,
        "decision": None,
        "emotion": "CALM",
        "thoughts": "",
        "log": [],
        "alive": True,
        "skip_research": False,
    }

    print("Running one full cycle  (calls Anthropic + yfinance)...")
    print("-" * 64)

    try:
        result = graph.invoke(state)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except Exception as exc:
        print(f"\nFATAL: {exc}")
        import traceback as tb

        tb.print_exc()
        sys.exit(1)

    print()
    print("=" * 64)
    print("  RESULT")
    print("=" * 64)
    dec = result.get("decision") or {}
    print(f"  Emotion     : {result.get('emotion')}")
    print(f"  Confidence  : {result.get('confidence', 0):.0%}")
    print(f"  Research    : {result.get('research_iterations', 0)} iteration(s)")
    print(f"  Action      : {dec.get('action')} {dec.get('symbol') or ''}")
    print(f"  Allocation  : {dec.get('allocation_pct', 0)}%")
    print(f"  Reasoning   : {(dec.get('reasoning') or '')[:100]}")
    print(f"  Thoughts    : {(result.get('thoughts') or '')[:120]}")
    print(f"  Intel       : {(dec.get('market_intel') or '')[:100]}")
    print(f"  Alive       : {result.get('alive', True)}")
    print()
    print("  Portfolio after :")
    print(f"    Cash       ${p.cash:.2f}")
    print(f"    Positions  {dict(p.positions)}")
    print(f"    Total      ${p.total_value():.2f}")
    print()
    log = result.get("log", [])
    print(f"  Log ({len(log)} entries):")
    for e in log:
        lvl = e.get("level", "info").upper()
        t = e["time"][11:19]
        print(f"    [{t}] [{lvl:8s}] {e['message'][:90]}")


# LangGraph Studio compatibility — module-level compiled graph
agent_graph = build_graph()
