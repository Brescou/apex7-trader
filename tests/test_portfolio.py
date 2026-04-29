"""Unit tests for ``Portfolio`` sell validation."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data import Portfolio


def _p_with_aapl() -> Portfolio:
    p = Portfolio()
    with p._lock:
        p.positions["AAPL"] = {"shares": 1.0, "avg_price": 100.0}
        p.cash = 500.0
    return p


def test_sell_rejects_zero_price() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 100, 0.0)
    assert r["success"] is False
    assert "AAPL" in p.positions


def test_sell_rejects_negative_price() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 100, -5.0)
    assert r["success"] is False


def test_sell_rejects_nan_price() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 100, float("nan"))
    assert r["success"] is False


def test_sell_normal_price() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 100, 150.0)
    assert r["success"] is True
    assert "AAPL" not in p.positions
    assert not math.isnan(p.cash)


def test_sell_rejects_zero_pct() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 0, 150.0)
    assert r["success"] is False
    assert "AAPL" in p.positions


def test_sell_rejects_pct_over_100() -> None:
    p = _p_with_aapl()
    r = p.sell("AAPL", 100.5, 150.0)
    assert r["success"] is False
    assert "AAPL" in p.positions
