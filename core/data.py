"""core.data — Portfolio and LiveFeed classes for APEX-7.

This module is the canonical location for Portfolio and LiveFeed.
The root-level data.py remains for backward compatibility during migration.
"""

import json
import logging
import math
import os
import threading
from datetime import datetime

import yfinance as yf

from config import (
    DEATH_THRESHOLD,
    INITIAL_BALANCE,
    MAX_ALLOC_PCT,
    MAX_PYRAMID_LAYERS,
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
        self.positions: dict[str, dict] = {}  # {symbol: {shares, avg_price, layers?}}
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
        self.high_watermarks: dict[str, float] = {}

    def fetch_prices(self, symbols: list[str] | None = None) -> dict[str, float]:
        syms = list(WATCHLIST) if symbols is None else symbols
        prices = {}

        if USE_LIVEFEED:
            try:
                if self._livefeed is None or self._livefeed_symbols != syms:
                    self._livefeed = LiveFeed(syms)
                    self._livefeed_symbols = list(syms)
                result = self._livefeed.fetch()
                if result:
                    with self._lock:
                        self.last_prices = result
                    return result
            except Exception:
                pass

        try:
            tickers = yf.Tickers(" ".join(syms))
            for sym in syms:
                try:
                    prices[sym] = float(tickers.tickers[sym].fast_info.last_price)
                except Exception:
                    prices[sym] = self.last_prices.get(sym, 0.0)
        except Exception as e:
            self.log(f"Price fetch error: {e}", "error")
            prices = {s: self.last_prices.get(s, 0.0) for s in syms}
        with self._lock:
            self.last_prices = prices
        return prices

    def _total_value_unlocked(self, prices: dict[str, float] | None) -> float:
        """Return cash + mark-to-market positions. Caller must hold ``self._lock``."""

        p = prices if prices is not None else self.last_prices
        positions_value = sum(
            pos["shares"] * p.get(sym, pos["avg_price"]) for sym, pos in self.positions.items()
        )
        return self.cash + positions_value

    def total_value(self, prices: dict[str, float] | None = None) -> float:
        with self._lock:
            return self._total_value_unlocked(prices)

    def buy(self, symbol: str, amount_usd: float, price: float) -> dict:
        with self._lock:
            if price <= 0:
                return {"success": False, "error": "Invalid price"}
            max_amount = self.cash * (MAX_ALLOC_PCT / 100)
            amount_usd = min(amount_usd, max_amount, self.cash)
            if amount_usd < 1:
                return {"success": False, "error": "Insufficient cash"}
            px = float(price)
            new_shares = amount_usd / px

            if symbol in self.positions:
                existing = self.positions[symbol]
                layers = int(existing.get("layers", 1))
                if layers >= MAX_PYRAMID_LAYERS:
                    return {
                        "success": False,
                        "error": f"max pyramid layers ({MAX_PYRAMID_LAYERS}) reached",
                    }
                old_shares = float(existing["shares"])
                old_avg = float(existing.get("avg_price", existing.get("avg_cost", 0)))
                total_shares = old_shares + new_shares
                new_avg = (old_shares * old_avg + new_shares * px) / total_shares
                existing["avg_price"] = new_avg
                existing["shares"] = total_shares
                existing["layers"] = layers + 1
                self.cash -= amount_usd
                trade_shares = new_shares
            else:
                self.cash -= amount_usd
                self.positions[symbol] = {
                    "shares": new_shares,
                    "avg_price": px,
                    "layers": 1,
                }
                trade_shares = new_shares
                fp = px
                if not math.isnan(fp) and fp > 0:
                    self.high_watermarks[symbol] = max(self.high_watermarks.get(symbol, fp), fp)

            trade = {
                "time": datetime.now().isoformat(),
                "action": "BUY",
                "symbol": symbol,
                "shares": round(trade_shares, 6),
                "price": round(px, 2),
                "amount": round(amount_usd, 2),
            }
            self.trade_history.append(trade)
            result = {"success": True, **trade}
        self.save_state()
        return result

    def sell(self, symbol: str, sell_pct: float, price: float) -> dict:
        with self._lock:
            try:
                px = float(price)
            except (TypeError, ValueError):
                logger.warning("Rejecting sell %s at invalid price %s", symbol, price)
                return {"success": False, "error": f"invalid price: {price}"}
            if px <= 0 or math.isnan(px):
                logger.warning("Rejecting sell %s at invalid price %s", symbol, price)
                return {"success": False, "error": f"invalid price: {price}"}
            try:
                sp = float(sell_pct)
            except (TypeError, ValueError):
                logger.warning("Rejecting sell %s: invalid sell_pct=%s", symbol, sell_pct)
                return {"success": False, "error": f"invalid sell_pct: {sell_pct}"}
            if math.isnan(sp) or not (0 < sp <= 100):
                logger.warning("Rejecting sell %s: invalid sell_pct=%s", symbol, sell_pct)
                return {"success": False, "error": f"invalid sell_pct: {sell_pct}"}
            sell_pct = sp
            if symbol not in self.positions:
                return {"success": False, "error": "No position"}
            pos = self.positions[symbol]
            shares = pos["shares"] * (sell_pct / 100)
            amount = shares * px
            self.cash += amount
            if sell_pct >= 100:
                del self.positions[symbol]
                self.high_watermarks.pop(symbol, None)
            else:
                self.positions[symbol]["shares"] -= shares
            trade = {
                "time": datetime.now().isoformat(),
                "action": "SELL",
                "symbol": symbol,
                "shares": round(shares, 6),
                "price": round(px, 2),
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
            val = self._total_value_unlocked(prices)
            self.value_history.append({"time": datetime.now().isoformat(), "value": val})
            if val > self.peak_value:
                self.peak_value = val

    def check_death(self, prices: dict[str, float], *, discord_mode: str | None = None) -> bool:
        # Portfolio dies exactly once — Discord alert on transition only.
        with self._lock:
            val = self._total_value_unlocked(prices)
            was_dead = self.is_dead
            self.is_dead = val < DEATH_THRESHOLD
            dead_now = self.is_dead
        if dead_now and not was_dead:
            try:
                if discord_mode is None or str(discord_mode).lower() == "sim":
                    return dead_now
                from core.notifications import alert_death

                alert_death(portfolio_value=val, mode=str(discord_mode))
            except Exception:
                pass
        return dead_now

    def update_watermarks(self, prices: dict[str, float]) -> None:
        """Raise per-symbol high watermark for open positions (trailing stop-loss)."""
        with self._lock:
            for sym in list(self.positions.keys()):
                raw = prices.get(sym)
                try:
                    q = float(raw)
                except (TypeError, ValueError):
                    continue
                if math.isnan(q) or q <= 0:
                    continue
                prev = self.high_watermarks.get(sym, q)
                self.high_watermarks[sym] = max(prev, q)

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
                "high_watermarks": {
                    sym: self.high_watermarks[sym]
                    for sym in self.positions
                    if sym in self.high_watermarks
                },
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
            hw = state.get("high_watermarks") or {}
            if isinstance(hw, dict):
                self.high_watermarks = {k: float(v) for k, v in hw.items() if k in self.positions}
            else:
                self.high_watermarks = {}
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
