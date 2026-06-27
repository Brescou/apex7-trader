"""core.backtest — Historical backtest on real yfinance data for APEX-7."""

import pandas as pd
import yfinance as yf

from config import COMMISSION_PCT, SLIPPAGE_PCT
from core import metrics
from core.indicators import rsi


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
    close_list = [float(x) for x in close]
    df["RSI_14"] = [rsi(close_list[: i + 1]) for i in range(len(close_list))]

    df["MA_20"] = close.rolling(20).mean()
    df["MA_50"] = close.rolling(50).mean()

    # MACD/Bollinger use the same EMA (adjust=False) and sample-std conventions
    # as the scalar helpers in ``core.indicators`` (macd / bollinger_bands), so
    # the last column values match what the live technician + terminal see.
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

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
    total_return_pct = (
        (final_value - initial_cash) / initial_cash * 100 if initial_cash > 0 else 0.0
    )

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

    return {
        "final_value": final_value,
        "total_return_pct": total_return_pct,
        "win_rate": win_rate,
        "max_drawdown_pct": metrics.max_drawdown(equity_curve) * 100,
        "sharpe_ratio": metrics.sharpe_ratio(equity_curve),
    }


def _simulate(
    df: pd.DataFrame,
    symbol: str,
    strategy: str,
    initial_cash: float,
    stop_loss_pct: float,
) -> tuple[list[dict], list[float]]:
    """Run the per-bar RSI trade simulation over an indicator-annotated frame.

    Returns ``(trades, equity_curve)``. Any open position is closed at the last
    bar's close so each run settles to cash. Shared by ``run_backtest`` and
    ``walk_forward_backtest`` so both use identical execution logic.
    """
    trades: list[dict] = []
    equity_curve: list[float] = [initial_cash]
    cash = initial_cash
    position_shares: float = 0.0
    position_price: float = 0.0
    in_position = False

    for idx, row in df.iterrows():
        rsi_val = row.get("RSI_14", 50.0)
        price = float(row["Close"])
        if price <= 0:
            continue

        if in_position and position_price > 0:
            loss_pct = (price - position_price) / position_price
            if loss_pct <= -stop_loss_pct:
                effective_sell = price * (1 - SLIPPAGE_PCT)
                proceeds = position_shares * effective_sell
                commission = proceeds * COMMISSION_PCT
                cash += proceeds - commission
                trades.append(
                    {
                        "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
                        "action": "SELL",
                        "symbol": symbol,
                        "price": price,
                        "reason": "stop_loss",
                    }
                )
                in_position = False
                position_shares = 0.0
                position_price = 0.0

        buy_signal = rsi_val < 30
        sell_signal = rsi_val > 70

        if strategy == "multi":
            tech_buy = rsi_val < 28
            anlst_buy = rsi_val < 32
            buy_signal = tech_buy and anlst_buy

            tech_sell = rsi_val > 72
            anlst_sell = rsi_val > 68
            sell_signal = tech_sell and anlst_sell

        if buy_signal and not in_position and cash > 1:
            alloc = cash * 0.95
            effective_buy = price * (1 + SLIPPAGE_PCT)
            commission = alloc * COMMISSION_PCT
            shares = alloc / effective_buy
            cash -= alloc + commission
            position_shares = shares
            position_price = effective_buy
            in_position = True
            trades.append(
                {
                    "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
                    "action": "BUY",
                    "symbol": symbol,
                    "price": price,
                    "reason": "rsi_oversold",
                }
            )

        elif sell_signal and in_position:
            effective_sell = price * (1 - SLIPPAGE_PCT)
            proceeds = position_shares * effective_sell
            commission = proceeds * COMMISSION_PCT
            cash += proceeds - commission
            trades.append(
                {
                    "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
                    "action": "SELL",
                    "symbol": symbol,
                    "price": price,
                    "reason": "rsi_overbought",
                }
            )
            in_position = False
            position_shares = 0.0
            position_price = 0.0

        portfolio_value = cash + (position_shares * price if in_position else 0.0)
        equity_curve.append(portfolio_value)

    if in_position and len(df) > 0:
        last_price = float(df["Close"].iloc[-1])
        effective_close = last_price * (1 - SLIPPAGE_PCT)
        final_proceeds = position_shares * effective_close
        cash += final_proceeds - final_proceeds * COMMISSION_PCT
        if equity_curve:
            equity_curve[-1] = cash

    return trades, equity_curve


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

    if len(df) < 15:
        metrics = _compute_metrics([initial_cash], [], initial_cash)
        return {
            "symbol": symbol,
            "period": period,
            "strategy": strategy,
            "trades": [],
            "n_trades": 0,
            "equity_curve": [initial_cash],
            "benchmark_return_pct": 0.0,
            "vs_benchmark": 0.0,
            **metrics,
        }

    trades, equity_curve = _simulate(df, symbol, strategy, initial_cash, stop_loss_pct)

    benchmark_return_pct = 0.0
    try:
        spy_df = fetch_historical("SPY", period=period)
        if len(spy_df) >= 2:
            spy_start = float(spy_df["Close"].iloc[0])
            spy_end = float(spy_df["Close"].iloc[-1])
            if spy_start > 0:
                benchmark_return_pct = (spy_end - spy_start) / spy_start * 100
    except Exception:
        pass

    metrics = _compute_metrics(equity_curve, trades, initial_cash)
    vs_benchmark = metrics["total_return_pct"] - benchmark_return_pct

    return {
        "symbol": symbol,
        "period": period,
        "strategy": strategy,
        "trades": trades,
        "n_trades": len(trades),
        "equity_curve": equity_curve,
        "benchmark_return_pct": benchmark_return_pct,
        "vs_benchmark": vs_benchmark,
        **metrics,
    }


def compare_strategies(symbol: str, period: str = "6mo") -> dict:
    """Run both 'simple' and 'multi' strategies, return both results."""
    simple_result = run_backtest(symbol, strategy="simple", period=period)
    multi_result = run_backtest(symbol, strategy="multi", period=period)
    return {
        "symbol": symbol,
        "period": period,
        "simple": simple_result,
        "multi": multi_result,
    }


def walk_forward_backtest(
    symbol: str,
    strategy: str = "simple",
    period: str = "1y",
    n_folds: int = 4,
    initial_cash: float = 1000.0,
    stop_loss_pct: float = 0.05,
) -> dict:
    """Out-of-sample robustness check: run the strategy on sequential folds.

    The price history is split into ``n_folds`` contiguous, non-overlapping
    windows. Each fold is simulated independently from ``initial_cash`` so a
    great run on one stretch can't mask poor behaviour elsewhere. Returns the
    per-fold results plus aggregates (mean return, % of profitable folds, and a
    ``consistency`` score = fraction of folds beating breakeven).

    Indicators are computed once over the full series before slicing so RSI at
    a fold's first bars still reflects prior history (no warm-up cliff).
    """
    df = fetch_historical(symbol, period=period)
    df = compute_indicators(df)

    n = len(df)
    if n < max(2 * n_folds, 30) or n_folds < 2:
        return {
            "symbol": symbol,
            "period": period,
            "strategy": strategy,
            "n_folds": 0,
            "folds": [],
            "mean_return_pct": 0.0,
            "pct_profitable_folds": 0.0,
            "consistency": 0.0,
            "note": "insufficient data for walk-forward",
        }

    fold_size = n // n_folds
    folds: list[dict] = []
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_folds - 1 else n
        seg = df.iloc[start:end]
        if len(seg) < 2:
            continue
        trades, equity_curve = _simulate(seg, symbol, strategy, initial_cash, stop_loss_pct)
        m = _compute_metrics(equity_curve, trades, initial_cash)
        folds.append(
            {
                "fold": i + 1,
                "start_date": (
                    str(seg.index[0].date()) if hasattr(seg.index[0], "date") else str(seg.index[0])
                ),
                "end_date": (
                    str(seg.index[-1].date())
                    if hasattr(seg.index[-1], "date")
                    else str(seg.index[-1])
                ),
                "n_trades": len(trades),
                "total_return_pct": m["total_return_pct"],
                "win_rate": m["win_rate"],
                "max_drawdown_pct": m["max_drawdown_pct"],
                "sharpe_ratio": m["sharpe_ratio"],
            }
        )

    returns = [f["total_return_pct"] for f in folds]
    n_profitable = sum(1 for r in returns if r > 0)
    mean_return = sum(returns) / len(returns) if returns else 0.0
    consistency = (n_profitable / len(folds)) if folds else 0.0

    return {
        "symbol": symbol,
        "period": period,
        "strategy": strategy,
        "n_folds": len(folds),
        "folds": folds,
        "mean_return_pct": mean_return,
        "pct_profitable_folds": consistency * 100.0,
        "consistency": consistency,
    }
