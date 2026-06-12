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


def ema(prices: object, period: int) -> list[float]:
    """Exponential moving average series (``adjust=False`` convention).

    Seeds with the first close (matches pandas ``ewm(..., adjust=False)`` used
    by :mod:`core.backtest`). Returns one value per input price, or ``[]`` for
    an empty input.
    """
    seq = _coerce_prices(prices)
    if not seq:
        return []
    k = 2.0 / (period + 1)
    out = [seq[0]]
    for p in seq[1:]:
        out.append(p * k + out[-1] * (1 - k))
    return out


def macd(
    prices: object,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float, float, float]:
    """MACD of a close series — returns ``(macd_line, signal_line, histogram)``.

    Uses the same EMA convention as :mod:`core.backtest` so the latest values
    match ``compute_indicators``' ``MACD`` / ``MACD_signal`` / ``MACD_hist``
    columns. Returns ``(0.0, 0.0, 0.0)`` when fewer than ``slow + signal``
    prices are available (insufficient data).
    """
    seq = _coerce_prices(prices)
    if len(seq) < slow + signal:
        return (0.0, 0.0, 0.0)
    ema_fast = ema(seq, fast)
    ema_slow = ema(seq, slow)
    macd_series = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_series = ema(macd_series, signal)
    macd_v = macd_series[-1]
    signal_v = signal_series[-1]
    return (macd_v, signal_v, macd_v - signal_v)


def bollinger_bands(
    prices: object,
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[float, float, float]:
    """Bollinger Bands of a close series — returns ``(upper, mid, lower)``.

    ``mid`` is the simple moving average over ``period``; the bands sit
    ``num_std`` sample standard deviations (ddof=1, pandas convention) away.
    Returns ``(0.0, 0.0, 0.0)`` when fewer than ``period`` prices are
    available (insufficient data).
    """
    seq = _coerce_prices(prices)
    if len(seq) < period:
        return (0.0, 0.0, 0.0)
    window = seq[-period:]
    mid = sum(window) / period
    if period > 1:
        var = sum((x - mid) ** 2 for x in window) / (period - 1)
    else:
        var = 0.0
    std = var**0.5
    return (mid + num_std * std, mid, mid - num_std * std)


def bb_position(price: float, prices: object, period: int = 20, num_std: float = 2.0) -> str:
    """Label where ``price`` sits relative to the Bollinger Bands.

    Returns ``"upper"`` (>= upper band), ``"lower"`` (<= lower band), or
    ``"mid"`` (inside / insufficient data).
    """
    upper, mid, lower = bollinger_bands(prices, period, num_std)
    if upper == 0.0 and lower == 0.0:
        return "mid"
    if price >= upper:
        return "upper"
    if price <= lower:
        return "lower"
    return "mid"
