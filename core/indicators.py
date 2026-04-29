"""core.indicators — shared technical indicators for APEX-7.

Single canonical RSI implementation used across agents, backtest, and market_data.
"""


def _coerce_prices(prices: object) -> list[float]:
    """Normalize ``list``, ``tuple``, pandas ``Series``, or ndarray-like to ``list[float]``."""
    if prices is None:
        return []
    if isinstance(prices, (str, bytes)):
        raise TypeError("prices must be a numeric sequence")
    if isinstance(prices, list):
        return [float(x) for x in prices]
    if hasattr(prices, "tolist"):
        return [float(x) for x in prices.tolist()]
    return [float(x) for x in prices]


def rsi(prices: object, period: int = 14) -> float:
    """Compute RSI from closing prices (same formula as live agents).

    Accepts ``list[float]``, ``tuple``, pandas ``Series``, or any sequence with ``tolist``.

    Uses the last ``period + 1`` closes; averages gains/losses over ``period`` steps.
    Returns ``50.0`` if fewer than ``period + 1`` prices (insufficient data).
    """
    seq = _coerce_prices(prices)
    if len(seq) < period + 1:
        return 50.0
    window = seq[-(period + 1) :]
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(window)):
        delta = window[i] - window[i - 1]
        if delta > 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
