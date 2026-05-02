"""Grille de performance des ETF sectoriels SPDR."""

import logging
import time

import pandas as pd

from market_data.caches import SECTOR_CACHE_SEC, _sector_perf_cache, _sector_perf_lock
from market_data.compat import yf

logger = logging.getLogger("apex7.market_data")

_SECTOR_ETFS: dict[str, str] = {
    "Tech": "XLK",
    "Finance": "XLF",
    "Energy": "XLE",
    "Health": "XLV",
    "Consumer": "XLY",
    "Industrial": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Comm": "XLC",
    "Staples": "XLP",
}


def _sector_pct_change_from_download(etf: str, period: str) -> float | None:
    """Return percent change first→last close for one ETF/period; ``None`` on failure."""
    try:
        df = yf.download(
            etf,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        if df is None or len(df) < 2:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        closes = df["Close"].dropna()
        if len(closes) < 2:
            return None
        first = float(closes.iloc[0])
        last = float(closes.iloc[-1])
        if first == 0:
            return None
        pct = (last - first) / first * 100.0
        return round(float(pct), 2)
    except Exception:
        logger.debug("sector performance failed for %s %s", etf, period, exc_info=False)
        return None


def fetch_sector_performance(
    periods: list[str] | None = None,
) -> dict[str, dict[str, float | None]]:
    """Fetch performance of each sector ETF over several yfinance periods.

    Cached 5 minutes per distinct ``periods`` list.
    """
    if periods is None:
        periods = ["1d", "5d", "1mo"]
    cache_key = "|".join(periods)
    with _sector_perf_lock:
        now = time.time()
        cached = _sector_perf_cache.get("data")
        if (
            cached is not None
            and _sector_perf_cache.get("key") == cache_key
            and (now - float(_sector_perf_cache.get("ts") or 0)) < SECTOR_CACHE_SEC
        ):
            return {k: dict(v) for k, v in cached.items()}

    result: dict[str, dict[str, float | None]] = {}
    for name, etf in _SECTOR_ETFS.items():
        result[name] = {}
        for period in periods:
            result[name][period] = _sector_pct_change_from_download(etf, period)

    with _sector_perf_lock:
        _sector_perf_cache["data"] = result
        _sector_perf_cache["key"] = cache_key
        _sector_perf_cache["ts"] = time.time()
    return {k: dict(v) for k, v in result.items()}
