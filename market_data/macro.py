"""Barre macro VIX / SPY / DXY — cache 60s."""

import time
from datetime import datetime

from config import MACRO_SYMBOLS

from market_data.caches import (
    _macro_cache,
    _macro_lock,
    macro_ttl,
    record_yf_failure,
    record_yf_success,
    yf_circuit_open,
)
from market_data.compat import yf
from market_data.finnhub import fetch_finnhub_quote


def _macro_finnhub_overlay(stale: dict) -> dict:
    """Refresh plain-ticker macro symbols via Finnhub when yfinance is down.

    ``^VIX`` / ``DX-Y.NYB`` are skipped (unsupported on Finnhub free tier);
    their stale values are carried over untouched.
    """
    result = dict(stale)
    for label, ticker_sym in MACRO_SYMBOLS.items():
        q = fetch_finnhub_quote(ticker_sym)
        if q is None:
            continue
        change_pct = q["change_pct"]
        direction = "up" if change_pct > 0.05 else ("down" if change_pct < -0.05 else "flat")
        result[label] = {"price": q["price"], "change_pct": change_pct, "direction": direction}
    return result


def fetch_macro() -> dict:
    """
    Fetch VIX, SPY, DXY via yfinance.
    Returns price, change_pct, direction per symbol + updated_at timestamp.
    Cached 60s. Falls back to last known value on failure.
    """
    with _macro_lock:
        now = time.time()
        if _macro_cache["data"] is not None and (now - _macro_cache["ts"]) < macro_ttl():
            return _macro_cache["data"]

        if yf_circuit_open():
            return _macro_finnhub_overlay(_macro_cache["data"] or {})

        result: dict = {}
        try:
            for label, ticker_sym in MACRO_SYMBOLS.items():
                hist = yf.Ticker(ticker_sym).history(period="5d", interval="1d")
                if hist.empty or len(hist) < 2:
                    result[label] = {"price": None, "change_pct": 0.0, "direction": "flat"}
                    continue
                closes = hist["Close"].tolist()
                price = round(closes[-1], 2)
                prev = closes[-2]
                change_pct = round((price - prev) / prev * 100, 2) if prev else 0.0
                if change_pct > 0.05:
                    direction = "up"
                elif change_pct < -0.05:
                    direction = "down"
                else:
                    direction = "flat"
                result[label] = {"price": price, "change_pct": change_pct, "direction": direction}

            record_yf_success()
            result["updated_at"] = datetime.now().strftime("%H:%M:%S")
            _macro_cache["data"] = result
            _macro_cache["ts"] = now
        except Exception:
            record_yf_failure()
            if _macro_cache["data"] is not None:
                return _macro_cache["data"]

        return result
