"""BacktestEngine — self-contained simulation engine for APEX-7 backtesting.

No LLM calls, no network, no modifications to agent.py global state.
Uses a local GBM + RSI engine that mirrors the agent sim logic.
"""

import math
import random
from typing import Any

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


# ── RSI helper ────────────────────────────────────────────────────────────────

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


# ── BacktestEngine ────────────────────────────────────────────────────────────

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
        # trade_history entries use keys: time, action, symbol, price
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
