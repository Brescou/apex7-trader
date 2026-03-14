"""BacktestEngine — self-contained simulation engine for APEX-7 backtesting.

No LLM calls, no modifications to agent.py global state.

Two modes:
- BacktestEngine (legacy): GBM synthetic price simulation
- run_backtest() (new): real yfinance historical data with RSI rules
"""

import math
import random
from typing import Any

import pandas as pd
import yfinance as yf

from config import DEATH_THRESHOLD, INITIAL_BALANCE, MAX_POSITIONS, WATCHLIST
from data import Portfolio

# ── Scenario presets ─────────────────────────────────────────────────────────

_SCENARIOS: dict[str, dict[str, float]] = {
    "Bull Market":      {"drift": 0.0005,  "vol": 0.02},
    "Bear Market":      {"drift": -0.0003, "vol": 0.025},
    "High Volatility":  {"drift": 0.0,     "vol": 0.05},
    "Flat Market":      {"drift": 0.0,     "vol": 0.005},
}

_BASE_PRICES: dict[str, float] = {
    "AAPL": 185.0,
    "MSFT": 415.0,
    "GOOG": 165.0,
    "AMZN": 185.0,
    "TSLA": 250.0,
}


# ── RSI helper (legacy, list-based) ──────────────────────────────────────────

def _rsi(prices: list[float], period: int = 14) -> float:
    """Compute RSI from a price series. Returns 50.0 if insufficient data."""
    if len(prices) < period + 1:
        return 50.0
    window = prices[-(period + 1):]
    gains, losses = [], []
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


# ── BacktestEngine (legacy — used by dashboard) ───────────────────────────────

class BacktestEngine:
    def __init__(self, scenario: str, config: dict[str, Any]) -> None:
        self.scenario = scenario
        self.config = config or {}
        params = _SCENARIOS.get(scenario, _SCENARIOS["Bull Market"])
        self.drift = params["drift"]
        self.vol = params["vol"]
        self.max_alloc_pct = float(self.config.get("max_alloc_pct", 25))

    def run(self, n_cycles: int = 100) -> dict:
        portfolio = Portfolio()

        # Price + history per symbol for RSI
        prices: dict[str, float] = {sym: _BASE_PRICES.get(sym, 100.0) for sym in WATCHLIST}
        price_history: dict[str, list[float]] = {sym: [prices[sym]] for sym in WATCHLIST}
        portfolio_history: list[float] = [INITIAL_BALANCE]
        trade_log: list[dict] = []

        for _ in range(n_cycles):
            if portfolio.is_dead:
                break

            # GBM step
            for sym in WATCHLIST:
                change = self.drift + self.vol * random.gauss(0, 1)
                prices[sym] = max(prices[sym] * (1 + change), 0.01)
                price_history[sym].append(prices[sym])

            # RSI signals — evaluate each symbol
            for sym in WATCHLIST:
                if portfolio.is_dead:
                    break
                rsi_val = _rsi(price_history[sym])

                if rsi_val < 35 and sym not in portfolio.positions and len(portfolio.positions) < MAX_POSITIONS:
                    alloc = portfolio.total_value(prices) * (self.max_alloc_pct / 100)
                    slip = 1 + random.uniform(-0.001, 0.001)
                    buy_price = prices[sym] * slip
                    result = portfolio.buy(sym, alloc, buy_price)
                    if result["success"]:
                        trade_log.append({
                            "message": f"BUY {sym} @ ${buy_price:.2f} RSI={rsi_val:.1f}",
                            "level": "info",
                        })

                elif rsi_val > 65 and sym in portfolio.positions:
                    slip = 1 + random.uniform(-0.001, 0.001)
                    sell_price = prices[sym] * slip
                    result = portfolio.sell(sym, 100, sell_price)
                    if result["success"]:
                        trade_log.append({
                            "message": f"SELL {sym} @ ${sell_price:.2f} RSI={rsi_val:.1f}",
                            "level": "info",
                        })

            portfolio.record_value(prices)
            portfolio.check_death(prices)
            portfolio_history.append(portfolio.total_value(prices))

        # ── Metrics ──────────────────────────────────────────────────────────
        final_value = portfolio.total_value(prices)
        return_pct = (final_value - INITIAL_BALANCE) / INITIAL_BALANCE * 100

        # Win rate: match each SELL to the most recent BUY for the same symbol
        history = portfolio.trade_history
        pnl_list: list[float] = []
        for sell in (t for t in history if t.get("action") == "SELL"):
            sym = sell.get("symbol")
            sell_price = sell.get("price", 0.0)
            sell_time = sell.get("time", "")
            prior_buys = [
                t for t in history
                if t.get("action") == "BUY"
                and t.get("symbol") == sym
                and t.get("time", "") <= sell_time
            ]
            if prior_buys:
                buy_price = prior_buys[-1].get("price", sell_price)
                if buy_price > 0:
                    pnl_list.append((sell_price - buy_price) / buy_price)

        win_rate = (sum(1 for p in pnl_list if p > 0) / len(pnl_list) * 100) if pnl_list else 0.0

        # Sharpe ratio (annualised)
        if len(portfolio_history) > 1:
            returns = [
                (portfolio_history[i] - portfolio_history[i - 1]) / portfolio_history[i - 1]
                for i in range(1, len(portfolio_history))
                if portfolio_history[i - 1] > 0
            ]
            if len(returns) > 1:
                mean_r = sum(returns) / len(returns)
                std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / len(returns))
                sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        # Max drawdown
        peak = portfolio_history[0]
        max_drawdown = 0.0
        for v in portfolio_history:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

        trades_count = len([t for t in history if t.get("action") in ("BUY", "SELL")])

        return {
            "return_pct":        return_pct,
            "sharpe":            sharpe,
            "max_drawdown":      max_drawdown,
            "survived":          not portfolio.is_dead,
            "portfolio_history": portfolio_history,
            "trades_count":      trades_count,
            "win_rate":          win_rate,
            "trade_log":         trade_log,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# NEW PUBLIC API — real yfinance data
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_historical(
    symbol: str,
    period: str = "6mo",
    interval: str = "1d",
) -> pd.DataFrame:
    """Download OHLCV data from yfinance. Returns empty DataFrame on failure."""
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
        if df is None or df.empty:
            return pd.DataFrame()
        # Flatten MultiIndex columns if present (yfinance 0.2+)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.dropna(inplace=True)
        return df
    except Exception:
        return pd.DataFrame()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical indicators to an OHLCV DataFrame.

    Columns added: RSI_14, MA_20, MA_50, MACD, MACD_signal, MACD_hist,
                   BB_upper, BB_lower.
    Returns df unchanged if fewer than 20 rows.
    """
    if df is None or len(df) < 15:
        return df

    df = df.copy()
    close = df["Close"]

    # ── RSI 14 (Wilder smoothing = EMA with alpha=1/14) ──────────────────────
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    alpha = 1.0 / 14
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["RSI_14"] = 100.0 - (100.0 / (1.0 + rs))
    df["RSI_14"] = df["RSI_14"].fillna(50.0)

    # ── Moving averages ───────────────────────────────────────────────────────
    df["MA_20"] = close.rolling(20).mean()
    df["MA_50"] = close.rolling(50).mean()

    # ── MACD (12/26/9 EMA) ───────────────────────────────────────────────────
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    # ── Bollinger Bands (20 SMA ± 2σ) ────────────────────────────────────────
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["BB_upper"] = sma20 + 2 * std20
    df["BB_lower"] = sma20 - 2 * std20

    return df


def _compute_metrics(
    equity_curve: list[float],
    trades: list[dict],
    initial_cash: float,
) -> dict:
    """Shared metrics computation for run_backtest."""
    final_value = equity_curve[-1] if equity_curve else initial_cash
    total_return_pct = (final_value - initial_cash) / initial_cash * 100 if initial_cash > 0 else 0.0

    # Win rate from matched BUY->SELL pairs
    pnl_list: list[float] = []
    buy_prices: dict[str, float] = {}
    for t in trades:
        if t["action"] == "BUY":
            buy_prices[t["symbol"]] = t["price"]
        elif t["action"] == "SELL" and t["symbol"] in buy_prices:
            bp = buy_prices.pop(t["symbol"])
            if bp > 0:
                pnl_list.append((t["price"] - bp) / bp)
    win_rate = (sum(1 for p in pnl_list if p > 0) / len(pnl_list) * 100) if pnl_list else 0.0

    # Max drawdown
    peak = equity_curve[0] if equity_curve else initial_cash
    max_drawdown_pct = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        if dd > max_drawdown_pct:
            max_drawdown_pct = dd

    # Sharpe ratio (annualised, daily returns)
    sharpe_ratio = 0.0
    if len(equity_curve) > 2:
        daily_returns = [
            (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
            for i in range(1, len(equity_curve))
            if equity_curve[i - 1] > 0
        ]
        if len(daily_returns) > 1:
            mean_r = sum(daily_returns) / len(daily_returns)
            variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
            std_r = math.sqrt(variance)
            sharpe_ratio = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

    return {
        "final_value":       final_value,
        "total_return_pct":  total_return_pct,
        "win_rate":          win_rate,
        "max_drawdown_pct":  max_drawdown_pct,
        "sharpe_ratio":      sharpe_ratio,
    }


def run_backtest(
    symbol: str,
    strategy: str = "simple",
    period: str = "6mo",
    initial_cash: float = 1000.0,
    stop_loss_pct: float = 0.05,
) -> dict:
    """Run a deterministic backtest on real yfinance data.

    strategy="simple": RSI<30 -> BUY, RSI>70 -> SELL
    strategy="multi":  same rules + both TECH and ANLST must agree (majority vote sim)
    """
    df = fetch_historical(symbol, period=period)
    df = compute_indicators(df)

    trades: list[dict] = []
    equity_curve: list[float] = [initial_cash]
    cash = initial_cash
    position_shares: float = 0.0
    position_price: float = 0.0
    in_position = False

    if len(df) < 15:
        # Insufficient data — return empty result
        metrics = _compute_metrics([initial_cash], [], initial_cash)
        return {
            "symbol":               symbol,
            "period":               period,
            "strategy":             strategy,
            "trades":               [],
            "n_trades":             0,
            "equity_curve":         [initial_cash],
            "benchmark_return_pct": 0.0,
            "vs_benchmark":         0.0,
            **metrics,
        }

    for idx, row in df.iterrows():
        rsi = row.get("RSI_14", 50.0)
        price = float(row["Close"])
        if price <= 0:
            continue

        # Stop-loss check
        if in_position and position_price > 0:
            loss_pct = (price - position_price) / position_price
            if loss_pct <= -stop_loss_pct:
                proceeds = position_shares * price
                cash += proceeds
                trades.append({
                    "date":    str(idx.date()) if hasattr(idx, "date") else str(idx),
                    "action":  "SELL",
                    "symbol":  symbol,
                    "price":   price,
                    "reason":  "stop_loss",
                })
                in_position = False
                position_shares = 0.0
                position_price = 0.0

        # Strategy signal
        buy_signal = rsi < 30
        sell_signal = rsi > 70

        if strategy == "multi":
            # Simulated majority vote: TECH uses RSI<28, ANLST uses RSI<32
            # Both must agree to trigger a buy (effective threshold: RSI<28)
            tech_buy   = rsi < 28
            anlst_buy  = rsi < 32
            buy_signal = tech_buy and anlst_buy

            tech_sell   = rsi > 72
            anlst_sell  = rsi > 68
            sell_signal = tech_sell and anlst_sell

        if buy_signal and not in_position and cash > 1:
            alloc = cash * 0.95  # invest 95% of available cash
            shares = alloc / price
            cash -= alloc
            position_shares = shares
            position_price = price
            in_position = True
            trades.append({
                "date":    str(idx.date()) if hasattr(idx, "date") else str(idx),
                "action":  "BUY",
                "symbol":  symbol,
                "price":   price,
                "reason":  "rsi_oversold",
            })

        elif sell_signal and in_position:
            proceeds = position_shares * price
            cash += proceeds
            trades.append({
                "date":    str(idx.date()) if hasattr(idx, "date") else str(idx),
                "action":  "SELL",
                "symbol":  symbol,
                "price":   price,
                "reason":  "rsi_overbought",
            })
            in_position = False
            position_shares = 0.0
            position_price = 0.0

        # Mark-to-market equity
        portfolio_value = cash + (position_shares * price if in_position else 0.0)
        equity_curve.append(portfolio_value)

    # Close any open position at last price
    if in_position and len(df) > 0:
        last_price = float(df["Close"].iloc[-1])
        cash += position_shares * last_price
        if equity_curve:
            equity_curve[-1] = cash

    # ── Benchmark: SPY same period ────────────────────────────────────────────
    benchmark_return_pct = 0.0
    try:
        spy_df = fetch_historical("SPY", period=period)
        if len(spy_df) >= 2:
            spy_start = float(spy_df["Close"].iloc[0])
            spy_end   = float(spy_df["Close"].iloc[-1])
            if spy_start > 0:
                benchmark_return_pct = (spy_end - spy_start) / spy_start * 100
    except Exception:
        pass

    metrics = _compute_metrics(equity_curve, trades, initial_cash)
    vs_benchmark = metrics["total_return_pct"] - benchmark_return_pct

    return {
        "symbol":               symbol,
        "period":               period,
        "strategy":             strategy,
        "trades":               trades,
        "n_trades":             len(trades),
        "equity_curve":         equity_curve,
        "benchmark_return_pct": benchmark_return_pct,
        "vs_benchmark":         vs_benchmark,
        **metrics,
    }


def compare_strategies(symbol: str, period: str = "6mo") -> dict:
    """Run both 'simple' and 'multi' strategies, return both results."""
    simple_result = run_backtest(symbol, strategy="simple", period=period)
    multi_result  = run_backtest(symbol, strategy="multi",  period=period)
    return {
        "symbol":  symbol,
        "period":  period,
        "simple":  simple_result,
        "multi":   multi_result,
    }
