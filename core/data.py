"""core.data — Portfolio and LiveFeed classes for APEX-7.

This module is the canonical location for Portfolio and LiveFeed.
The root-level data.py remains for backward compatibility during migration.
"""

import json
import logging
import os
import threading
from datetime import datetime

import yfinance as yf

from config import (
    DEATH_THRESHOLD,
    INITIAL_BALANCE,
    MAX_ALLOC_PCT,
    PORTFOLIO_SAVE_ENABLED,
    PORTFOLIO_STATE_PATH,
    USE_LIVEFEED,
    WATCHLIST,
)

logger = logging.getLogger("apex7.portfolio")


class Portfolio:
    def __init__(self):
        self._lock = threading.RLock()
        self.cash = float(INITIAL_BALANCE)
        self.positions: dict[str, dict] = {}  # {symbol: {"shares": float, "avg_price": float}}
        self.trade_history: list[dict] = []
        self.value_history: list[dict] = [
            {"time": datetime.now().isoformat(), "value": float(INITIAL_BALANCE)}
        ]
        self.agent_log: list[dict] = []
        self.is_dead = False
        self.last_prices: dict[str, float] = {}
        self.peak_value: float = float(INITIAL_BALANCE)
        self._livefeed: "LiveFeed | None" = None
        self._livefeed_symbols: list[str] = []

    def fetch_prices(self, symbols: list[str] | None = None) -> dict[str, float]:
        symbols = symbols or WATCHLIST
        prices = {}

        if USE_LIVEFEED:
            try:
                if self._livefeed is None or self._livefeed_symbols != symbols:
                    self._livefeed = LiveFeed(symbols)
                    self._livefeed_symbols = list(symbols)
                result = self._livefeed.fetch()
                if result:
                    with self._lock:
                        self.last_prices = result
                    return result
            except Exception:
                pass

        try:
            tickers = yf.Tickers(" ".join(symbols))
            for sym in symbols:
                try:
                    prices[sym] = float(tickers.tickers[sym].fast_info.last_price)
                except Exception:
                    prices[sym] = self.last_prices.get(sym, 0.0)
        except Exception as e:
            self.log(f"Price fetch error: {e}", "error")
            prices = {s: self.last_prices.get(s, 0.0) for s in symbols}
        with self._lock:
            self.last_prices = prices
        return prices

    def total_value(self, prices: dict[str, float] | None = None) -> float:
        with self._lock:
            p = prices if prices is not None else self.last_prices
            positions_value = sum(
                pos["shares"] * p.get(sym, pos["avg_price"]) for sym, pos in self.positions.items()
            )
            return self.cash + positions_value

    def buy(self, symbol: str, amount_usd: float, price: float) -> dict:
        with self._lock:
            if price <= 0:
                return {"success": False, "error": "Invalid price"}
            max_amount = self.cash * (MAX_ALLOC_PCT / 100)
            amount_usd = min(amount_usd, max_amount, self.cash)
            if amount_usd < 1:
                return {"success": False, "error": "Insufficient cash"}
            if symbol in self.positions:
                return {"success": False, "error": "position already open"}
            shares = amount_usd / price
            self.cash -= amount_usd
            self.positions[symbol] = {"shares": shares, "avg_price": price}
            trade = {
                "time": datetime.now().isoformat(),
                "action": "BUY",
                "symbol": symbol,
                "shares": round(shares, 6),
                "price": round(price, 2),
                "amount": round(amount_usd, 2),
            }
            self.trade_history.append(trade)
            result = {"success": True, **trade}
        self.save_state()
        return result

    def sell(self, symbol: str, sell_pct: float, price: float) -> dict:
        with self._lock:
            if symbol not in self.positions:
                return {"success": False, "error": "No position"}
            pos = self.positions[symbol]
            sell_pct = min(max(sell_pct, 0), 100)
            shares = pos["shares"] * (sell_pct / 100)
            amount = shares * price
            self.cash += amount
            if sell_pct >= 100:
                del self.positions[symbol]
            else:
                self.positions[symbol]["shares"] -= shares
            trade = {
                "time": datetime.now().isoformat(),
                "action": "SELL",
                "symbol": symbol,
                "shares": round(shares, 6),
                "price": round(price, 2),
                "amount": round(amount, 2),
            }
            self.trade_history.append(trade)
            result = {"success": True, **trade}
        self.save_state()
        return result

    def open_symbols(self) -> list[str]:
        with self._lock:
            return list(self.positions.keys())

    def closed_trades_since(self, ts: str) -> list[dict]:
        with self._lock:
            return [t for t in self.trade_history if t["action"] == "SELL" and t["time"] >= ts]

    def record_value(self, prices: dict[str, float]):
        with self._lock:
            val = self.total_value(prices)
            self.value_history.append({"time": datetime.now().isoformat(), "value": val})
            if val > self.peak_value:
                self.peak_value = val

    def check_death(self, prices: dict[str, float]) -> bool:
        val = self.total_value(prices)
        with self._lock:
            self.is_dead = val < DEATH_THRESHOLD
        return self.is_dead

    def log(self, message: str, level: str = "info"):
        entry = {"time": datetime.now().isoformat(), "message": message, "level": level}
        with self._lock:
            self.agent_log.append(entry)
        formatted = f"[APEX-7/{level.upper()}] {message}"
        lvl = level.lower()
        if lvl in ("error", "critical", "warning"):
            logger.warning("%s", formatted)
        else:
            logger.info("%s", formatted)

    def save_state(self, path: str | None = None) -> None:
        if not PORTFOLIO_SAVE_ENABLED:
            return
        path = str(path or PORTFOLIO_STATE_PATH)
        with self._lock:
            state = {
                "cash": self.cash,
                "positions": dict(self.positions),
                "trade_history": list(self.trade_history[-50:]),
                "value_history": list(self.value_history[-200:]),
                "peak_value": self.peak_value,
            }
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(state, f)
            os.replace(tmp_path, path)
        except Exception as e:
            self.log(f"save_state error: {e}", "error")

    def load_state(self, path: str | None = None) -> bool:
        path = path or PORTFOLIO_STATE_PATH
        if not os.path.exists(path):
            return False
        try:
            with open(path) as f:
                state = json.load(f)
        except Exception as e:
            self.log(f"load_state: corrupt file at {path}, starting fresh ({e})", "warning")
            return False
        with self._lock:
            self.cash = float(state.get("cash", self.cash))
            self.positions = state.get("positions", self.positions)
            self.trade_history = state.get("trade_history", self.trade_history)[-50:]
            self.value_history = state.get("value_history", self.value_history)[-200:]
            self.peak_value = float(state.get("peak_value", self.peak_value))
        return True


class LiveFeed:
    def __init__(self, symbols: list[str] | str):
        if isinstance(symbols, str):
            symbols = [symbols]
        self.symbols = symbols

    def update_symbols(self, symbols: list[str]) -> None:
        self.symbols = symbols

    def fetch(self) -> dict[str, float]:
        result = {}
        for sym in self.symbols:
            try:
                ticker = yf.Ticker(sym)
                hist = ticker.history(period="1d", interval="1m")
                if not hist.empty:
                    result[sym] = float(hist["Close"].iloc[-1])
            except Exception:
                pass
        return result
