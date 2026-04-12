"""Smoke tests for APEX-7.

Run with:  uv run pytest tests/test_smoke.py -v
Legacy:    uv run python tests/test_smoke.py
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["SIMULATION_MODE"] = "true"


# ─────────────────────────────────────────────────────────────────────────────


def test_imports():
    import config  # noqa: F401
    from core.data import Portfolio, LiveFeed  # noqa: F401
    from core.backtest import run_backtest  # noqa: F401
    from core.registry import get_graph  # noqa: F401


def test_portfolio_basic(portfolio):
    assert portfolio.cash == 1000.0, f"Expected 1000.0 cash, got {portfolio.cash}"

    result = portfolio.buy("AAPL", 200.0, 100.0)
    assert result["success"], f"buy failed: {result}"
    assert "AAPL" in portfolio.positions
    assert portfolio.cash < 1000.0

    symbols = portfolio.open_symbols()
    assert "AAPL" in symbols, f"open_symbols missing AAPL: {symbols}"

    result = portfolio.sell("AAPL", 100, 110.0)
    assert result["success"], f"sell failed: {result}"
    assert "AAPL" not in portfolio.positions

    assert len(portfolio.trade_history) == 2
    assert portfolio.trade_history[0]["action"] == "BUY"
    assert portfolio.trade_history[1]["action"] == "SELL"


def test_portfolio_multi_symbol(portfolio):
    r1 = portfolio.buy("AAPL", 200.0, 100.0)
    assert r1["success"], f"first buy failed: {r1}"

    r2 = portfolio.buy("AAPL", 100.0, 105.0)
    assert not r2["success"], f"duplicate buy should fail but got: {r2}"
    assert "already open" in r2.get("error", "").lower() or not r2["success"]

    r3 = portfolio.buy("MSFT", 200.0, 400.0)
    assert r3["success"], f"MSFT buy failed: {r3}"
    assert len(portfolio.positions) == 2


def test_simple_graph_build():
    from agents.simple import build_graph as build_simple_graph
    from core.data import Portfolio

    g = build_simple_graph(Portfolio())
    nodes = list(g.nodes)
    expected = [
        "load_memory",
        "fetch_data",
        "analyze",
        "research",
        "risk_check",
        "execute",
        "save_memory",
        "skip",
    ]
    for node in expected:
        assert node in nodes, f"Missing node '{node}' in simple graph. Got: {nodes}"


def test_multi_graph_build():
    from agents.multi import build_multi_graph
    from core.data import Portfolio

    g = build_multi_graph(Portfolio())
    nodes = list(g.nodes)
    expected = [
        "load_memory",
        "fetch_data",
        "supervisor",
        "technician",
        "analyst",
        "risk_manager",
        "macro_watcher",
        "arbitrate",
        "risk_check",
        "execute",
        "save_memory",
        "skip",
    ]
    for node in expected:
        assert node in nodes, f"Missing node '{node}' in multi graph. Got: {nodes}"


def test_simulation_cycle():
    from agents.simple import build_graph as build_simple_graph
    from agents.shared.nodes import _sim_mode
    from core.data import Portfolio

    _sim_mode["enabled"] = True

    p = Portfolio()
    g = build_simple_graph(p)

    initial = {
        "balance": p.cash,
        "positions": dict(p.positions),
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

    result = g.invoke(initial)
    assert result is not None, "graph.invoke returned None"
    assert "alive" in result, "result missing 'alive' key"
    assert "log" in result, "result missing 'log' key"
    assert len(result["log"]) > 0, "no log entries produced"


def test_backtest_run():
    from core.backtest import run_backtest

    result = run_backtest("AAPL", period="1mo")
    required_keys = [
        "symbol",
        "final_value",
        "total_return_pct",
        "win_rate",
        "max_drawdown_pct",
        "sharpe_ratio",
        "n_trades",
        "benchmark_return_pct",
        "equity_curve",
    ]
    for k in required_keys:
        assert k in result, f"run_backtest result missing key: '{k}'"

    assert result["symbol"] == "AAPL"
    assert isinstance(result["equity_curve"], list)
    assert len(result["equity_curve"]) > 0
    assert isinstance(result["n_trades"], int)


def test_sqlite_schema():
    import sqlite3
    from pathlib import Path

    db_path = Path(__file__).parent.parent / "trades.db"
    assert db_path.exists(), f"trades.db not found at {db_path}"

    con = sqlite3.connect(db_path)
    cursor = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    con.close()

    required_tables = {"trades", "patterns", "agent_memory", "postmortem"}
    for table in required_tables:
        assert table in tables, f"Missing table '{table}'. Found: {tables}"


def test_app_import():
    from dashboard import create_app

    a = create_app()
    assert a is not None, "create_app() returned None"


# ─────────────────────────────────────────────────────────────────────────────
# Legacy runner (for backward compat with `uv run python tests/test_smoke.py`)

_results: list[tuple[str, bool, str]] = []


def _run(name: str, fn) -> bool:
    try:
        fn()
        _results.append((name, True, ""))
        print(f"  [PASS] {name}")
        return True
    except Exception as e:
        tb = traceback.format_exc()
        _results.append((name, False, str(e)))
        print(f"  [FAIL] {name}: {e}")
        print(tb)
        return False


if __name__ == "__main__":
    from core.data import Portfolio

    print("=" * 60)
    print("  APEX-7 Smoke Tests")
    print("=" * 60)

    tests = [
        ("test_imports", test_imports),
        ("test_portfolio_basic", lambda: test_portfolio_basic(Portfolio())),
        ("test_portfolio_multi_symbol", lambda: test_portfolio_multi_symbol(Portfolio())),
        ("test_simple_graph_build", test_simple_graph_build),
        ("test_multi_graph_build", test_multi_graph_build),
        ("test_simulation_cycle", test_simulation_cycle),
        ("test_backtest_run", test_backtest_run),
        ("test_sqlite_schema", test_sqlite_schema),
        ("test_app_import", test_app_import),
    ]

    for name, fn in tests:
        _run(name, fn)

    print()
    print("=" * 60)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"  Results: {passed}/{len(_results)} passed")
    if failed:
        print("  FAILED tests:")
        for name, ok, err in _results:
            if not ok:
                print(f"    - {name}: {err}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
