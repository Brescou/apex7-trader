"""Lightweight tests to cover isolated modules (coverage toward CI threshold)."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_leaderboard_run_all_mocked() -> None:
    """``Leaderboard.run_all`` hits engine loop without Yahoo."""
    fake = {
        "return_pct": 1.2,
        "sharpe": 0.4,
        "win_rate": 55.0,
        "max_drawdown": -5.0,
        "trades_count": 2,
        "survived": True,
    }
    with patch("leaderboard.BacktestEngine") as eng:
        eng.return_value.run.return_value = fake
        from leaderboard import Leaderboard

        rows = Leaderboard().run_all("Bull Market")
    assert len(rows) == 4
    assert rows[0]["agent_id"] in ("CONSERVATIVE", "BALANCED", "AGGRESSIVE", "APEX-7")


def test_seed_live_price_history_uses_yfinance() -> None:
    """Seeding pulls daily rows and sets technician history (network-free)."""
    import pandas as pd

    import agents.shared.nodes as nodes

    idx = pd.date_range("2026-01-01", periods=20, freq="D")
    df = pd.DataFrame({"Close": [100.0 + i * 0.1 for i in range(20)]}, index=idx)
    with patch("agents.shared.nodes.yf.download", return_value=df):
        nodes._live_price_history.clear()
        nodes._last_price_date.clear()
        nodes._live_price_history_seeded = False
        nodes._seed_live_price_history()
    try:
        assert nodes._live_price_history_seeded
        for sym in nodes.WATCHLIST:
            assert len(nodes._live_price_history.get(sym, [])) >= 1
    finally:
        nodes._live_price_history.clear()
        nodes._last_price_date.clear()
        nodes._live_price_history_seeded = False
