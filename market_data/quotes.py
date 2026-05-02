"""Cotations watchlist + indicateurs (RSI, MA20) — cache 10s."""

import time

from core.indicators import rsi

from market_data.caches import _watchlist_cache, _watchlist_lock, watchlist_ttl
from market_data.compat import yf


def fetch_watchlist_prices(symbols: list[str]) -> dict:
    """
    Fetch live prices + indicators for a list of symbols.
    Returns price, change_pct, change_abs, volume, high_52w, low_52w, rsi_14, above_ma20.
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

        result: dict = {}
        for sym in symbols:
            try:
                hist = yf.Ticker(sym).history(period="1y", interval="1d")
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
                result[sym] = {
                    "price": price,
                    "change_pct": change_pct,
                    "change_abs": change_abs,
                    "volume": volume,
                    "high_52w": high_52w,
                    "low_52w": low_52w,
                    "rsi_14": rsi_14 if rsi_14 is not None else 50.0,
                    "above_ma20": bool(above_ma20),
                }
            except Exception:
                result[sym] = {
                    "price": None,
                    "change_pct": 0.0,
                    "change_abs": 0.0,
                    "volume": 0,
                    "high_52w": None,
                    "low_52w": None,
                    "rsi_14": 50.0,
                    "above_ma20": False,
                }

        _watchlist_cache["data"] = result
        _watchlist_cache["key"] = cache_key
        _watchlist_cache["ts"] = now
        return result
