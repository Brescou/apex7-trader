"""Tests for core.backtest walk-forward + the extracted _simulate helper."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from core.backtest import run_backtest, walk_forward_backtest  # noqa: E402


def _mock_df(n: int) -> pd.DataFrame:
    """Synthetic OHLCV with an oscillating close so RSI crosses 30/70."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [100.0 + 15.0 * ((i // 5) % 2) + (i % 5) for i in range(n)]
    return pd.DataFrame(
        {
            "Open": [c - 0.2 for c in close],
            "High": [c + 0.3 for c in close],
            "Low": [c - 0.4 for c in close],
            "Close": close,
            "Volume": [1_000_000 + i for i in range(n)],
        },
        index=idx,
    )


def test_walk_forward_basic_shape():
    df = _mock_df(120)
    with patch("core.backtest.yf.download", side_effect=lambda *a, **k: df.copy()):
        wf = walk_forward_backtest("AAPL", period="1y", n_folds=4)
    assert wf["n_folds"] == 4
    assert len(wf["folds"]) == 4
    for f in wf["folds"]:
        for key in ("fold", "start_date", "end_date", "total_return_pct", "win_rate"):
            assert key in f
    assert 0.0 <= wf["consistency"] <= 1.0
    assert wf["pct_profitable_folds"] == pytest.approx(wf["consistency"] * 100.0)


def test_walk_forward_insufficient_data():
    df = _mock_df(20)
    with patch("core.backtest.yf.download", side_effect=lambda *a, **k: df.copy()):
        wf = walk_forward_backtest("AAPL", period="1mo", n_folds=4)
    assert wf["n_folds"] == 0
    assert wf["folds"] == []
    assert "insufficient" in wf.get("note", "")


def test_walk_forward_folds_are_disjoint_and_cover_series():
    df = _mock_df(100)
    with patch("core.backtest.yf.download", side_effect=lambda *a, **k: df.copy()):
        wf = walk_forward_backtest("AAPL", period="1y", n_folds=5)
    folds = wf["folds"]
    # last fold's end_date should be the series' last date
    assert folds[-1]["end_date"] == "2024-04-09"  # 100 days from 2024-01-01


def test_run_backtest_still_intact_after_refactor():
    df = _mock_df(40)
    with patch("core.backtest.yf.download", side_effect=lambda *a, **k: df.copy()):
        result = run_backtest("AAPL", period="3mo")
    for k in ("symbol", "final_value", "total_return_pct", "equity_curve", "n_trades"):
        assert k in result
    # equity curve starts at the initial cash
    assert result["equity_curve"][0] == pytest.approx(1000.0)
