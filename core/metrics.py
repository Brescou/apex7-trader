"""core.metrics — portfolio performance metrics shared by agents, backtest, and dashboard.

Pure functions over numeric sequences — no I/O, no imports from ``agents/`` or
``dashboard/`` (core dependency rule). Callers pass value histories or closed-trade
PnL lists as parameters.
"""

import math


def returns_from_values(values: list[float]) -> list[float]:
    """Per-period simple returns from a value series. Skips non-positive bases."""
    out: list[float] = []
    for prev, cur in zip(values, values[1:]):
        if prev > 0:
            out.append((cur - prev) / prev)
    return out


def sharpe_ratio(values: list[float], periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio (risk-free rate 0) from a value series."""
    rets = returns_from_values(values)
    if len(rets) < 2:
        return 0.0
    mean_r = sum(rets) / len(rets)
    var = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
    std_r = math.sqrt(var)
    if std_r == 0:
        return 0.0
    return mean_r / std_r * math.sqrt(periods_per_year)


def sortino_ratio(values: list[float], periods_per_year: int = 252) -> float:
    """Annualized Sortino ratio (downside deviation only) from a value series."""
    rets = returns_from_values(values)
    if len(rets) < 2:
        return 0.0
    mean_r = sum(rets) / len(rets)
    downside = [r for r in rets if r < 0]
    if not downside:
        return 0.0 if mean_r <= 0 else float("inf")
    dd_var = sum(r**2 for r in downside) / len(rets)
    dd_std = math.sqrt(dd_var)
    if dd_std == 0:
        return 0.0
    return mean_r / dd_std * math.sqrt(periods_per_year)


def max_drawdown(values: list[float]) -> float:
    """Maximum peak-to-trough drawdown as a fraction in [0, 1]."""
    peak = float("-inf")
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def realized_volatility(values: list[float], window: int = 20) -> float:
    """Std-dev of per-period returns over the trailing ``window`` periods.

    Returns 0.0 when fewer than 3 returns are available.
    """
    rets = returns_from_values(values)[-window:]
    if len(rets) < 3:
        return 0.0
    mean_r = sum(rets) / len(rets)
    var = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


def win_stats(pnl_fracs: list[float]) -> tuple[float, float, float]:
    """(win_rate, avg_win, avg_loss) from closed-trade fractional PnLs.

    ``avg_loss`` is returned as a positive magnitude. Trades with exactly 0 PnL
    count against the win rate but are excluded from the win/loss averages.
    Returns (0.0, 0.0, 0.0) on an empty list.
    """
    if not pnl_fracs:
        return 0.0, 0.0, 0.0
    wins = [p for p in pnl_fracs if p > 0]
    losses = [p for p in pnl_fracs if p < 0]
    win_rate = len(wins) / len(pnl_fracs)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    return win_rate, avg_win, avg_loss


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Kelly criterion optimal bet fraction; clamped to [0, 1].

    ``f* = (p·b − q) / b`` with ``b = avg_win / avg_loss``. Returns 0.0 when
    inputs are degenerate (no losses observed → b undefined, or avg_win ≤ 0).
    """
    if avg_win <= 0 or avg_loss <= 0:
        return 0.0
    b = avg_win / avg_loss
    f = (win_rate * b - (1 - win_rate)) / b
    return max(0.0, min(f, 1.0))
