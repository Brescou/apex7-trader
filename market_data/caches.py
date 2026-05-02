"""Caches mémoire et verrous (TTL) partagés par les sous-modules ``market_data``."""

import threading
from typing import Any

from config import MARKET_DATA_CACHE_SEC, WATCHLIST_CACHE_SEC

_macro_cache: dict = {"data": None, "ts": 0.0}
_macro_lock = threading.Lock()

_watchlist_cache: dict = {"data": None, "ts": 0.0, "key": ""}
_watchlist_lock = threading.Lock()

_sparkline_cache: dict = {}
_sparkline_lock = threading.Lock()

_comparison_cache: dict = {}
_comparison_lock = threading.Lock()

_ohlcv_cache: dict = {}
_ohlcv_lock = threading.Lock()

SPARKLINE_CACHE_SEC = 300
COMPARISON_CACHE_SEC = 300
OHLCV_CACHE_SEC = 300
SECTOR_CACHE_SEC = 300
CORR_MATRIX_CACHE_SEC = 300

_sector_perf_cache: dict[str, Any] = {"data": None, "ts": 0.0, "key": ""}
_sector_perf_lock = threading.Lock()

_corr_matrix_cache: dict[str, Any] = {"data": None, "ts": 0.0, "key": ""}
_corr_matrix_lock = threading.Lock()

_earnings_cache: dict[str, Any] = {"data": None, "ts": 0.0, "key": ""}
_earnings_lock = threading.Lock()
EARNINGS_TTL = 300  # 5 min


def macro_ttl() -> float:
    return float(MARKET_DATA_CACHE_SEC)


def watchlist_ttl() -> float:
    return float(WATCHLIST_CACHE_SEC)
