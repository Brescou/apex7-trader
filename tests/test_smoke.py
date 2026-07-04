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
    from agents.registry import get_graph  # noqa: F401


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
    assert r2["success"], f"pyramid buy should succeed: {r2}"
    aapl = portfolio.positions["AAPL"]
    assert aapl.get("layers", 1) == 2
    # avg_price uses effective_px (price × (1+SLIPPAGE_PCT)) for both legs.
    from config import SLIPPAGE_PCT

    ep1 = 100.0 * (1 + SLIPPAGE_PCT)
    ep2 = 105.0 * (1 + SLIPPAGE_PCT)
    exp_avg = 300.0 / (200.0 / ep1 + 100.0 / ep2)
    assert abs(float(aapl["avg_price"]) - exp_avg) < 1e-6

    r3 = portfolio.buy("MSFT", 200.0, 400.0)
    assert r3["success"], f"MSFT buy failed: {r3}"
    assert len(portfolio.positions) == 2


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
        # economist/geopolitician are the 5th/6th specialists (added after
        # the original 4) — a prior version of this list never checked for
        # them, so removing either from build_multi_graph() would not have
        # failed any test (Review Finding: coverage gap).
        "economist",
        "geopolitician",
        "arbitrate",
        "risk_check",
        "execute",
        "save_memory",
        "skip",
    ]
    for node in expected:
        assert node in nodes, f"Missing node '{node}' in multi graph. Got: {nodes}"


def test_simulation_cycle():
    """A full cycle writes trades/pending_evaluations/cycle_states — redirect
    ``_get_db_path`` to a temp file first so it never touches the project's
    real ``trades_sim.db``. Fixture-free (no ``tmp_db``) so the legacy
    ``python tests/test_smoke.py`` runner keeps working — same pattern as
    ``test_sqlite_schema`` above.
    """
    import tempfile
    from pathlib import Path

    import agents.shared.db as db_mod
    from agents.multi import build_multi_graph
    from agents.shared.nodes import _sim_mode
    from core.data import Portfolio

    _sim_mode["enabled"] = True

    p = Portfolio()
    g = build_multi_graph(p)

    initial = {
        "balance": p.cash,
        "positions": dict(p.positions),
        "portfolio_history": [],
        "prices": {},
        "news": "",
        "sentiment": {},
        "macro_indicators": {},
        "fear_greed": None,
        "earnings_calendar": {},
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
        "supervisor_brief": "",
        "agent_role": "",
        "agent_votes": [],
        "tech_vote": None,
        "analyst_vote": None,
        "risk_vote": None,
        "macro_vote": None,
        "arbitration": None,
    }

    orig_get_db_path = db_mod._get_db_path
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sim_cycle.db"
        db_mod._get_db_path = lambda: db_path
        try:
            db_mod._db_initialized_paths.discard(str(db_path))
            result = g.invoke(initial)
        finally:
            db_mod._get_db_path = orig_get_db_path
            db_mod._db_initialized_paths.discard(str(db_path))

    assert result is not None, "graph.invoke returned None"
    assert "alive" in result, "result missing 'alive' key"
    assert "log" in result, "result missing 'log' key"
    assert len(result["log"]) > 0, "no log entries produced"


def test_backtest_run():
    import pandas as pd
    from unittest.mock import patch

    from core.backtest import run_backtest

    # Synthetic OHLCV (~20 rows) — avoids live Yahoo Finance (Finding 5.5).
    n = 22
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    close_vals = [185.0 + 0.12 * i + 0.05 * (i % 7) for i in range(n)]
    df_mock = pd.DataFrame(
        {
            "Open": [c - 0.25 for c in close_vals],
            "High": [c + 0.35 for c in close_vals],
            "Low": [c - 0.45 for c in close_vals],
            "Close": close_vals,
            "Volume": [1_100_000 + i * 500 for i in range(n)],
        },
        index=idx,
    )

    def _fake_download(*_args, **_kwargs):
        return df_mock.copy()

    with patch("core.backtest.yf.download", side_effect=_fake_download):
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
    """Schema check against a temp DB — never touches the project ``trades.db``.

    Avoids pytest fixtures so the legacy ``python tests/test_smoke.py`` runner
    keeps working; the redirect mirrors the ``tmp_db`` fixture in conftest.
    """
    import sqlite3
    import tempfile
    from pathlib import Path

    import agents.shared.db as db_mod

    orig_get_db_path = db_mod._get_db_path
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "schema_check.db"
        db_mod._get_db_path = lambda: db_path
        try:
            db_mod._db_initialized_paths.discard(str(db_path))
            db_mod._ensure_db()
            assert db_path.is_file(), f"schema DB not created at {db_path}"

            con = sqlite3.connect(db_path)
            cursor = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            con.close()
        finally:
            db_mod._get_db_path = orig_get_db_path
            db_mod._db_initialized_paths.discard(str(db_path))

    required_tables = {"trades", "patterns", "agent_memory", "postmortem", "watchlist"}
    for table in required_tables:
        assert table in tables, f"Missing table '{table}'. Found: {tables}"


def test_agent_memory_has_trace_id():
    """Native schema must include ``trace_id`` so tests need no ALTER workaround.

    Regression guard for Review v5 Finding 5.2 — the previous schema lacked
    the column, which silently broke ``evaluate_pending_trades``.

    Avoids the ``tmp_db`` pytest fixture (same temp-DB redirect pattern as
    ``test_sqlite_schema`` above) so this guard also runs under the legacy
    fixture-free ``python tests/test_smoke.py`` runner — the prior version
    required ``tmp_db`` and was therefore silently absent from that runner's
    test list (Review Finding).
    """
    import sqlite3
    import tempfile
    from pathlib import Path

    import agents.shared.db as db_mod

    orig_get_db_path = db_mod._get_db_path
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trace_id_check.db"
        db_mod._get_db_path = lambda: db_path
        try:
            db_mod._db_initialized_paths.discard(str(db_path))
            db_mod._ensure_db()
            with sqlite3.connect(db_path) as con:
                cols = {r[1] for r in con.execute("PRAGMA table_info(agent_memory)").fetchall()}
        finally:
            db_mod._get_db_path = orig_get_db_path
            db_mod._db_initialized_paths.discard(str(db_path))

    assert "trace_id" in cols, (
        "agent_memory schema must include trace_id natively — "
        "remove any ALTER TABLE workaround in test fixtures."
    )


def test_app_import():
    """``create_app()`` calls ``start_controller()`` — a real Portfolio + a
    live agent thread + a postmortem thread that runs forever, all pointed
    at the real project ``trades_sim.db`` (default sim mode). Mocked so this
    smoke test verifies Dash wiring without spawning a background trading
    loop for the rest of the process.
    """
    from unittest.mock import patch

    from dashboard import create_app

    with patch("dashboard.controller.start_controller"):
        a = create_app()
    assert a is not None, "create_app() returned None"


def test_main_entrypoint_module():
    """Import ``main`` so entrypoint wiring is covered (CI coverage threshold).

    Same ``start_controller`` mock as ``test_app_import`` — importing
    ``main`` calls ``create_app()`` too, and ``create_app``'s
    ``_app_initialized`` guard means only the *first* call of either test
    actually reaches ``start_controller``, so both mock it defensively.
    """
    import importlib
    from unittest.mock import patch

    with patch("dashboard.controller.start_controller"):
        main_mod = importlib.import_module("main")
    assert main_mod.app is not None


def test_rsi_unified_backtest_and_live():
    """RSI list vs Series; compute_indicators matches scalar rsi on full series."""
    import pandas as pd

    from core.backtest import compute_indicators
    from core.indicators import rsi

    closes = [100.0 + i * 0.5 for i in range(30)]
    assert abs(rsi(closes) - rsi(pd.Series(closes))) < 1e-9

    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * len(closes),
        }
    )
    out = compute_indicators(df)
    last = float(out["RSI_14"].iloc[-1])
    assert (
        abs(last - rsi(closes)) < 1e-9
    ), f"compute_indicators RSI {last} vs rsi(closes) {rsi(closes)}"


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
        ("test_multi_graph_build", test_multi_graph_build),
        ("test_simulation_cycle", test_simulation_cycle),
        ("test_backtest_run", test_backtest_run),
        ("test_rsi_unified_backtest_and_live", test_rsi_unified_backtest_and_live),
        ("test_sqlite_schema", test_sqlite_schema),
        ("test_agent_memory_has_trace_id", test_agent_memory_has_trace_id),
        ("test_app_import", test_app_import),
        ("test_main_entrypoint_module", test_main_entrypoint_module),
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
