"""Grille de performance des ETF sectoriels SPDR."""

import logging
import threading
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

# Serializes the actual network fetch so concurrent cache-miss callers
# coalesce onto one fetch instead of each independently re-running the full
# batch of downloads (Review Finding: thundering herd).
_sector_fetch_lock = threading.Lock()


def _sector_pct_changes_from_batch_download(
    etfs: list[str], period: str
) -> dict[str, float | None]:
    """Percent change first→last close for many ETFs in ONE yf.download call.

    Replaces one yf.download per ETF (11 ETFs x 3 periods = 33 sequential
    downloads per refresh, Review Finding) with one batched call per period.
    """
    out: dict[str, float | None] = dict.fromkeys(etfs)
    try:
        df = yf.download(
            etfs,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
    except Exception:
        logger.debug("batch sector download failed for period %s", period, exc_info=False)
        return out
    if df is None or df.empty or not isinstance(df.columns, pd.MultiIndex):
        return out

    closes = df["Close"]
    for etf in etfs:
        if etf not in closes.columns:
            continue
        series = closes[etf].dropna()
        if len(series) < 2:
            continue
        first = float(series.iloc[0])
        last = float(series.iloc[-1])
        if first == 0:
            continue
        out[etf] = round((last - first) / first * 100.0, 2)
    return out


def fetch_sector_performance(
    periods: list[str] | None = None,
) -> dict[str, dict[str, float | None]]:
    """Fetch performance of each sector ETF over several yfinance periods.

    Cached 5 minutes per distinct ``periods`` list.
    """
    if periods is None:
        periods = ["1d", "5d", "1mo"]
    cache_key = "|".join(periods)

    def _cached_if_fresh() -> dict[str, dict[str, float | None]] | None:
        with _sector_perf_lock:
            now = time.time()
            cached = _sector_perf_cache.get("data")
            if (
                cached is not None
                and _sector_perf_cache.get("key") == cache_key
                and (now - float(_sector_perf_cache.get("ts") or 0)) < SECTOR_CACHE_SEC
            ):
                return {k: dict(v) for k, v in cached.items()}
        return None

    hit = _cached_if_fresh()
    if hit is not None:
        return hit

    with _sector_fetch_lock:
        # Re-check: another thread may have just finished fetching this same
        # ``periods`` combination while we were waiting for the fetch lock.
        hit = _cached_if_fresh()
        if hit is not None:
            return hit

        etfs = list(_SECTOR_ETFS.values())
        result: dict[str, dict[str, float | None]] = {name: {} for name in _SECTOR_ETFS}
        for period in periods:
            batch = _sector_pct_changes_from_batch_download(etfs, period)
            for name, etf in _SECTOR_ETFS.items():
                result[name][period] = batch.get(etf)

        with _sector_perf_lock:
            _sector_perf_cache["data"] = result
            _sector_perf_cache["key"] = cache_key
            _sector_perf_cache["ts"] = time.time()
        return {k: dict(v) for k, v in result.items()}
