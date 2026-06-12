"""Unit tests for core.metrics — pure performance metric functions."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.metrics import (  # noqa: E402
    kelly_fraction,
    max_drawdown,
    realized_volatility,
    returns_from_values,
    sharpe_ratio,
    sortino_ratio,
    win_stats,
)


def test_returns_from_values():
    assert returns_from_values([100.0, 110.0, 99.0]) == [0.1, -0.1]
    assert returns_from_values([]) == []
    assert returns_from_values([100.0]) == []
    # Non-positive bases are skipped
    assert returns_from_values([0.0, 100.0, 110.0]) == [0.1]


def test_sharpe_ratio_zero_cases():
    assert sharpe_ratio([]) == 0.0
    assert sharpe_ratio([100.0, 101.0]) == 0.0  # single return
    assert sharpe_ratio([100.0, 100.0, 100.0]) == 0.0  # zero std


def test_sharpe_ratio_positive_trend():
    values = [100.0 * (1.01**i) for i in range(20)]
    # Constant positive returns → std ~0 numerically, but jittered series works
    jittered = [v * (1 + (0.001 if i % 2 else -0.001)) for i, v in enumerate(values)]
    assert sharpe_ratio(jittered) > 0


def test_sortino_ratio():
    assert sortino_ratio([]) == 0.0
    # No downside, positive mean → inf
    assert sortino_ratio([100.0, 101.0, 102.0]) == float("inf")
    # Mixed returns → finite value
    val = sortino_ratio([100.0, 105.0, 95.0, 102.0])
    assert math.isfinite(val)


def test_max_drawdown():
    assert max_drawdown([]) == 0.0
    assert max_drawdown([100.0, 110.0, 120.0]) == 0.0
    assert abs(max_drawdown([100.0, 50.0, 100.0]) - 0.5) < 1e-9
    # Peak then trough: 120 → 60 = 50% DD
    assert abs(max_drawdown([100.0, 120.0, 60.0, 90.0]) - 0.5) < 1e-9


def test_realized_volatility():
    assert realized_volatility([]) == 0.0
    assert realized_volatility([100.0, 101.0, 102.0]) == 0.0  # only 2 returns
    flat = [100.0] * 10
    assert realized_volatility(flat) == 0.0
    noisy = [100.0, 105.0, 95.0, 110.0, 90.0, 100.0]
    assert realized_volatility(noisy) > 0.05


def test_win_stats():
    assert win_stats([]) == (0.0, 0.0, 0.0)
    win_rate, avg_win, avg_loss = win_stats([0.10, -0.05, 0.06, -0.03])
    assert abs(win_rate - 0.5) < 1e-9
    assert abs(avg_win - 0.08) < 1e-9
    assert abs(avg_loss - 0.04) < 1e-9
    # avg_loss is a positive magnitude
    assert avg_loss > 0


def test_kelly_fraction():
    # Degenerate inputs → 0
    assert kelly_fraction(0.5, 0.0, 0.05) == 0.0
    assert kelly_fraction(0.5, 0.08, 0.0) == 0.0
    # Coin flip with 2:1 payoff → f* = (0.5*2 - 0.5)/2 = 0.25
    assert abs(kelly_fraction(0.5, 0.10, 0.05) - 0.25) < 1e-9
    # Losing edge → clamped to 0
    assert kelly_fraction(0.3, 0.05, 0.05) == 0.0
    # Clamped to 1 max
    assert kelly_fraction(1.0, 0.10, 0.0001) <= 1.0
