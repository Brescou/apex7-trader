"""Cotations watchlist + indicateurs (RSI, MA20) — cache 10s."""

import time

from core.indicators import bb_position, macd, rsi

from market_data.caches import (
    _watchlist_cache,
    _watchlist_lock,
    record_yf_failure,
    record_yf_success,
    watchlist_ttl,
    yf_circuit_open,
)
from market_data.compat import yf
from market_data.finnhub import fetch_finnhub_quotes


def _finnhub_overlay(symbols: list[str], stale: dict) -> dict:
    """Try Finnhub for current prices when yfinance is down.

    Merges fresh price/change from Finnhub onto the stale cache (RSI, MA20,
    52w highs/lows kept from cache — Finnhub /quote only gives daily data).
    Returns stale unchanged when Finnhub returns nothing.
    """
    fresh = fetch_finnhub_quotes(symbols)
    if not fresh:
        return stale
    result = dict(stale)
    for sym, q in fresh.items():
        base = stale.get(sym, {})
        result[sym] = {
            "price": q["price"],
            "change_pct": q["change_pct"],
            "change_abs": q["change_abs"],
            "volume": base.get("volume", 0),
            "high_52w": base.get("high_52w"),
            "low_52w": base.get("low_52w"),
            "rsi_14": base.get("rsi_14", 50.0),
            "above_ma20": base.get("above_ma20", False),
            "macd_hist": base.get("macd_hist", 0.0),
            "bb_pos": base.get("bb_pos", "mid"),
        }
    return result


def fetch_watchlist_prices(symbols: list[str]) -> dict:
    """
    Fetch live prices + indicators for a list of symbols.
    Returns price, change_pct, change_abs, volume, high_52w, low_52w, rsi_14,
    above_ma20, macd_hist, bb_pos.
    Cached 10s per symbol set.
    """
    cache_key = ",".join(sorted(symbols))
    with _watchlist_lock:
        now = time.time()
        if (
            _watchlist_cache["data"] is not None
            and _watchlist_cache["key"] == cache_key
            and (now - _watchlist_cache["ts"]) < watchlist_ttl()
        ):
            return _watchlist_cache["data"]

        if yf_circuit_open():
            return _finnhub_overlay(symbols, _watchlist_cache["data"] or {})

        result: dict = {}
        for sym in symbols:
            try:
                hist = yf.Ticker(sym).history(period="1y", interval="1d")
                record_yf_success()
                if hist.empty or len(hist) < 2:
                    result[sym] = {
                        "price": None,
                        "change_pct": 0.0,
                        "change_abs": 0.0,
                        "volume": 0,
                        "high_52w": None,
                        "low_52w": None,
                        "rsi_14": None,
                        "above_ma20": False,
                        "macd_hist": 0.0,
                        "bb_pos": "mid",
                    }
                    continue
                closes = hist["Close"].tolist()
                volumes = hist["Volume"].tolist()
                price = round(closes[-1], 2)
                prev = closes[-2]
                change_abs = round(price - prev, 2)
                change_pct = round(change_abs / prev * 100, 2) if prev else 0.0
                volume = int(volumes[-1]) if volumes else 0
                high_52w = round(max(closes), 2)
                low_52w = round(min(closes), 2)
                rsi_14 = rsi(closes, 14)
                above_ma20 = (
                    price > (sum(closes[-20:]) / min(20, len(closes)))
                    if len(closes) >= 1
                    else False
                )
                _, _, macd_hist = macd(closes)
                bb_pos = bb_position(price, closes)
                result[sym] = {
                    "price": price,
                    "change_pct": change_pct,
                    "change_abs": change_abs,
                    "volume": volume,
                    "high_52w": high_52w,
                    "low_52w": low_52w,
                    "rsi_14": rsi_14 if rsi_14 is not None else 50.0,
                    "above_ma20": bool(above_ma20),
                    "macd_hist": round(macd_hist, 3),
                    "bb_pos": bb_pos,
                }
            except Exception:
                record_yf_failure()
                result[sym] = {
                    "price": None,
                    "change_pct": 0.0,
                    "change_abs": 0.0,
                    "volume": 0,
                    "high_52w": None,
                    "low_52w": None,
                    "rsi_14": 50.0,
                    "above_ma20": False,
                    "macd_hist": 0.0,
                    "bb_pos": "mid",
                }

        _watchlist_cache["data"] = result
        _watchlist_cache["key"] = cache_key
        _watchlist_cache["ts"] = now
        return result
