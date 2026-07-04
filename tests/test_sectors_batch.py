"""Tests for market_data/sectors.py batching + thundering-herd guard.

Covers the Review Finding at market_data/sectors.py:79 — 11 ETFs x 3
periods = 33 sequential yf.download calls per refresh, with no protection
against two concurrent cache-miss callers each re-running the full batch.
"""

import os
import sys
import threading
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data import caches, sectors  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_sector_state():
    caches._sector_perf_cache["data"] = None
    caches._sector_perf_cache["ts"] = 0.0
    caches._sector_perf_cache["key"] = ""
    yield
    caches._sector_perf_cache["data"] = None
    caches._sector_perf_cache["ts"] = 0.0
    caches._sector_perf_cache["key"] = ""


def _multiindex_close_df(tickers, n=10, base=100.0, end=110.0):
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    close = {t: np.linspace(base, end, n) for t in tickers}
    df = pd.DataFrame(close, index=idx)
    df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
    return df


def test_fetch_sector_performance_batches_one_download_per_period(monkeypatch):
    """11 ETFs x 1 period must be exactly 1 yf.download call, not 11."""
    idx_tickers = list(sectors._SECTOR_ETFS.values())

    def _fake_download(tickers, **_kwargs):
        return _multiindex_close_df(tickers)

    with patch("market_data.sectors.yf.download", side_effect=_fake_download) as mock_dl:
        out = sectors.fetch_sector_performance(["1mo"])

    assert mock_dl.call_count == 1
    for name, etf in sectors._SECTOR_ETFS.items():
        assert etf in idx_tickers
        assert out[name]["1mo"] == pytest.approx(10.0, rel=1e-9)


def test_fetch_sector_performance_missing_ticker_column_stays_none():
    """One ETF absent from the batched response (e.g. delisted) must not
    blow up the others' values.
    """
    tickers = list(sectors._SECTOR_ETFS.values())
    present = tickers[:-1]  # drop the last one

    def _fake_download(_tickers, **_kwargs):
        return _multiindex_close_df(present)

    with patch("market_data.sectors.yf.download", side_effect=_fake_download):
        out = sectors.fetch_sector_performance(["1mo"])

    missing_name = [n for n, e in sectors._SECTOR_ETFS.items() if e == tickers[-1]][0]
    present_name = [n for n, e in sectors._SECTOR_ETFS.items() if e == tickers[0]][0]
    assert out[missing_name]["1mo"] is None
    assert out[present_name]["1mo"] == pytest.approx(10.0, rel=1e-9)


def test_concurrent_cache_miss_coalesces_into_one_fetch():
    """Two threads racing past an expired cache must not each independently
    run the full batch of downloads — the second one should wait and then
    read the first one's freshly-cached result.
    """
    entered = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def _blocking_download(tickers, **_kwargs):
        call_count["n"] += 1
        entered.set()
        release.wait(timeout=2.0)
        return _multiindex_close_df(tickers)

    results: list[dict] = []

    def _run():
        results.append(sectors.fetch_sector_performance(["1mo"]))

    # Patch once, outside both threads — two independent `patch()` context
    # managers entering/exiting on the same global target from different
    # threads race each other's teardown and can leave the REAL yf.download
    # active mid-test.
    with patch("market_data.sectors.yf.download", side_effect=_blocking_download):
        t1 = threading.Thread(target=_run)
        t1.start()
        assert entered.wait(timeout=2.0), "first fetch never started"

        # Second caller arrives while the first is still mid-download — with
        # the thundering-herd guard it must block on _sector_fetch_lock
        # instead of starting a second full batch of downloads.
        t2 = threading.Thread(target=_run)
        t2.start()

        release.set()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

    assert not t1.is_alive() and not t2.is_alive()
    assert call_count["n"] == 1, "second caller must coalesce onto the first fetch, not re-download"
    assert len(results) == 2
    assert results[0] == results[1]
