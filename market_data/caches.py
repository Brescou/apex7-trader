"""Caches mémoire et verrous (TTL) partagés par les sous-modules ``market_data``."""

import logging
import threading
import time
from typing import Any

from config import MARKET_DATA_CACHE_SEC, WATCHLIST_CACHE_SEC

logger = logging.getLogger("apex7")

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


# ── yfinance circuit breaker ──────────────────────────────────────────────────
# After _YF_MAX_FAILURES consecutive errors, yfinance calls are skipped for
# _YF_PAUSE_SEC seconds and callers serve their stale cache instead.

_YF_MAX_FAILURES = 3
_YF_PAUSE_SEC = 60.0

_yf_circuit: dict = {"failures": 0, "paused_until": 0.0}
_yf_circuit_lock = threading.Lock()


def yf_circuit_open() -> bool:
    """Return True if yfinance calls should be skipped (circuit tripped)."""
    with _yf_circuit_lock:
        now = time.time()
        if _yf_circuit["paused_until"] > now:
            return True
        # Auto-reset once the pause window has elapsed
        if _yf_circuit["paused_until"] > 0:
            _yf_circuit["failures"] = 0
            _yf_circuit["paused_until"] = 0.0
        return False


def record_yf_failure() -> None:
    """Increment the consecutive-failure counter; trip the circuit when threshold reached."""
    with _yf_circuit_lock:
        _yf_circuit["failures"] += 1
        if _yf_circuit["failures"] >= _YF_MAX_FAILURES:
            _yf_circuit["paused_until"] = time.time() + _YF_PAUSE_SEC
            logger.warning(
                "market_data: yfinance circuit open after %d failures — pausing %.0fs",
                _yf_circuit["failures"],
                _YF_PAUSE_SEC,
            )


def record_yf_success() -> None:
    """Reset the consecutive-failure counter after a successful yfinance call."""
    with _yf_circuit_lock:
        _yf_circuit["failures"] = 0
        _yf_circuit["paused_until"] = 0.0
