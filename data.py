import threading
from datetime import datetime

import yfinance as yf

from config import DEATH_THRESHOLD, INITIAL_BALANCE, MAX_ALLOC_PCT, WATCHLIST


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

    def fetch_prices(self, symbols: list[str] | None = None) -> dict[str, float]:
        symbols = symbols or WATCHLIST
        prices = {}
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
                pos["shares"] * p.get(sym, pos["avg_price"])
                for sym, pos in self.positions.items()
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
            shares = amount_usd / price
            self.cash -= amount_usd
            if symbol in self.positions:
                pos = self.positions[symbol]
                total = pos["shares"] + shares
                self.positions[symbol] = {
                    "shares": total,
                    "avg_price": (pos["shares"] * pos["avg_price"] + shares * price) / total,
                }
            else:
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
            return {"success": True, **trade}

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
            return {"success": True, **trade}

    def record_value(self, prices: dict[str, float]):
        with self._lock:
            self.value_history.append(
                {"time": datetime.now().isoformat(), "value": self.total_value(prices)}
            )

    def check_death(self, prices: dict[str, float]) -> bool:
        val = self.total_value(prices)
        with self._lock:
            self.is_dead = val < DEATH_THRESHOLD
        return self.is_dead

    def log(self, message: str, level: str = "info"):
        entry = {"time": datetime.now().isoformat(), "message": message, "level": level}
        with self._lock:
            self.agent_log.append(entry)
        print(f"[APEX-7/{level.upper()}] {message}")
