"""core.indicators — shared technical indicators for APEX-7.

Single canonical RSI implementation used by agents, backtest, and market_data.
"""


def rsi(prices: list[float], period: int = 14) -> float:
    """Compute Wilder RSI from a list of closing prices.

    Returns 50.0 if insufficient data (fewer than period + 1 prices).
    """
    if len(prices) < period + 1:
        return 50.0
    window = prices[-(period + 1) :]
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
