"""Smoke tests for APEX-7 — no pytest, just assert + print.

Run with:  uv run python tests/test_smoke.py
Exit 0 if all pass, exit 1 on any failure.
"""

import os
import sys
import traceback

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Enable simulation mode before any agent import to avoid API calls
os.environ["SIMULATION_MODE"] = "true"

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


# ─────────────────────────────────────────────────────────────────────────────

def test_imports():
    import config          # noqa: F401
    import data            # noqa: F401
    import backtest        # noqa: F401
    import agent           # noqa: F401
    import agent_multi     # noqa: F401
    import graph_registry  # noqa: F401


def test_portfolio_basic():
    from data import Portfolio

    p = Portfolio()
    assert p.cash == 1000.0, f"Expected 1000.0 cash, got {p.cash}"

    result = p.buy("AAPL", 200.0, 100.0)
    assert result["success"], f"buy failed: {result}"
    assert "AAPL" in p.positions
    assert p.cash < 1000.0

    symbols = p.open_symbols()
    assert "AAPL" in symbols, f"open_symbols missing AAPL: {symbols}"

    result = p.sell("AAPL", 100, 110.0)
    assert result["success"], f"sell failed: {result}"
    assert "AAPL" not in p.positions

    assert len(p.trade_history) == 2
    assert p.trade_history[0]["action"] == "BUY"
    assert p.trade_history[1]["action"] == "SELL"


def test_portfolio_multi_symbol():
    from data import Portfolio

    p = Portfolio()
    # First buy succeeds
    r1 = p.buy("AAPL", 200.0, 100.0)
    assert r1["success"], f"first buy failed: {r1}"

    # Second buy on same symbol must fail (1 position per symbol)
    r2 = p.buy("AAPL", 100.0, 105.0)
    assert not r2["success"], f"duplicate buy should fail but got: {r2}"
    assert "already open" in r2.get("error", "").lower() or not r2["success"]

    # Different symbol succeeds
    r3 = p.buy("MSFT", 200.0, 400.0)
    assert r3["success"], f"MSFT buy failed: {r3}"
    assert len(p.positions) == 2


def test_simple_graph_build():
    import agent
    from data import Portfolio

    g = agent.build_graph(Portfolio())
    nodes = list(g.nodes)
    expected = ["load_memory", "fetch_data", "analyze", "research",
                "risk_check", "execute", "save_memory", "skip"]
    for node in expected:
        assert node in nodes, f"Missing node '{node}' in simple graph. Got: {nodes}"


def test_multi_graph_build():
    import agent_multi
    from data import Portfolio

    g = agent_multi.build_graph(Portfolio())
    nodes = list(g.nodes)
    expected = ["load_memory", "fetch_data", "supervisor", "technician",
                "analyst", "risk_manager", "macro_watcher", "arbitrate",
                "risk_check", "execute", "save_memory", "skip"]
    for node in expected:
        assert node in nodes, f"Missing node '{node}' in multi graph. Got: {nodes}"

    # stoploss_guard: not yet wired — handle gracefully
    if "stoploss_guard" not in nodes:
        print("    (stoploss_guard not yet in multi graph — expected, skipping)")


def test_simulation_cycle():
    import agent
    from agent import _sim_mode
    from data import Portfolio

    # Force simulation mode on
    _sim_mode["enabled"] = True

    p = Portfolio()
    g = agent.build_graph(p)

    initial = {
        "balance":             p.cash,
        "positions":           dict(p.positions),
        "portfolio_history":   [],
        "prices":              {},
        "news":                "",
        "sentiment":           {},
        "past_trades":         [],
        "known_patterns":      [],
        "round":               1,
        "confidence":          0.0,
        "research_iterations": 0,
        "decision":            None,
        "emotion":             "CALM",
        "thoughts":            "",
        "log":                 [],
        "alive":               True,
        "skip_research":       False,
    }

    result = g.invoke(initial)
    assert result is not None, "graph.invoke returned None"
    assert "alive" in result, "result missing 'alive' key"
    assert "log" in result, "result missing 'log' key"
    assert len(result["log"]) > 0, "no log entries produced"


def test_backtest_run():
    from backtest import run_backtest

    result = run_backtest("AAPL", period="1mo")
    required_keys = [
        "symbol", "final_value", "total_return_pct", "win_rate",
        "max_drawdown_pct", "sharpe_ratio", "n_trades",
        "benchmark_return_pct", "equity_curve",
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
    import app  # noqa: F401
    assert hasattr(app, "server") or hasattr(app, "app"), \
        "app module imported but missing 'server' or 'app' attribute"


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  APEX-7 Smoke Tests")
    print("=" * 60)

    tests = [
        ("test_imports",              test_imports),
        ("test_portfolio_basic",      test_portfolio_basic),
        ("test_portfolio_multi_symbol", test_portfolio_multi_symbol),
        ("test_simple_graph_build",   test_simple_graph_build),
        ("test_multi_graph_build",    test_multi_graph_build),
        ("test_simulation_cycle",     test_simulation_cycle),
        ("test_backtest_run",         test_backtest_run),
        ("test_sqlite_schema",        test_sqlite_schema),
        ("test_app_import",           test_app_import),
    ]

    for name, fn in tests:
        _run(name, fn)

    print()
    print("=" * 60)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"  Results: {passed}/{len(_results)} passed")
    if failed:
        print(f"  FAILED tests:")
        for name, ok, err in _results:
            if not ok:
                print(f"    - {name}: {err}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
