"""Tests for core.indicators — MACD, Bollinger Bands, EMA (pure functions)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from core.indicators import bb_position, bollinger_bands, ema, macd, rsi  # noqa: E402


def test_ema_seeds_with_first_value():
    assert ema([10.0], 12) == [10.0]
    out = ema([1.0, 2.0, 3.0], 2)
    assert out[0] == 1.0
    assert len(out) == 3
    # k = 2/3 for period 2: second = 2*2/3 + 1*1/3 = 5/3
    assert out[1] == pytest.approx(5.0 / 3.0)


def test_ema_empty():
    assert ema([], 10) == []


def test_macd_insufficient_data_returns_zeros():
    assert macd([1.0, 2.0, 3.0]) == (0.0, 0.0, 0.0)


def test_macd_histogram_sign_on_uptrend():
    # A steadily rising series → fast EMA above slow EMA → positive MACD line
    prices = [float(i) for i in range(1, 60)]
    macd_v, signal_v, hist = macd(prices)
    assert macd_v > 0
    assert hist == pytest.approx(macd_v - signal_v)


def test_macd_matches_backtest_convention():
    """The scalar macd() must equal pandas ewm(adjust=False) last values."""
    pd = pytest.importorskip("pandas")
    prices = [100 + (i % 7) - 3 for i in range(80)]
    close = pd.Series([float(p) for p in prices])
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    exp_macd = float(macd_line.iloc[-1])
    exp_signal = float(signal_line.iloc[-1])

    macd_v, signal_v, hist = macd(prices)
    assert macd_v == pytest.approx(exp_macd, abs=1e-9)
    assert signal_v == pytest.approx(exp_signal, abs=1e-9)
    assert hist == pytest.approx(exp_macd - exp_signal, abs=1e-9)


def test_bollinger_insufficient_data():
    assert bollinger_bands([1.0, 2.0], period=20) == (0.0, 0.0, 0.0)


def test_bollinger_bands_ordering_and_mid():
    prices = [10.0, 12.0, 14.0, 16.0, 18.0]
    upper, mid, lower = bollinger_bands(prices, period=5, num_std=2.0)
    assert mid == pytest.approx(14.0)  # mean of 10..18
    assert lower < mid < upper


def test_bollinger_matches_pandas_sample_std():
    pd = pytest.importorskip("pandas")
    prices = [float(p) for p in [10, 11, 9, 12, 8, 13, 7, 14, 6, 15]]
    close = pd.Series(prices)
    sma = close.rolling(5).mean()
    std = close.rolling(5).std()  # ddof=1 by default
    exp_upper = float((sma + 2 * std).iloc[-1])
    exp_lower = float((sma - 2 * std).iloc[-1])
    upper, mid, lower = bollinger_bands(prices, period=5, num_std=2.0)
    assert upper == pytest.approx(exp_upper, abs=1e-9)
    assert lower == pytest.approx(exp_lower, abs=1e-9)


def test_bb_position_labels():
    prices = [10.0, 11.0, 9.0, 12.0, 8.0]
    upper, mid, lower = bollinger_bands(prices, period=5)
    assert bb_position(upper + 1, prices, period=5) == "upper"
    assert bb_position(lower - 1, prices, period=5) == "lower"
    assert bb_position(mid, prices, period=5) == "mid"
    # insufficient data → mid
    assert bb_position(100.0, [1.0, 2.0], period=5) == "mid"


def test_rsi_still_canonical():
    # Sanity: rsi unchanged by the new additions
    assert rsi([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]) == 100.0
