"""External market data not sourced from yfinance (FRED, CNN Fear & Greed).

Thread-safe in-memory TTL caches; network errors are swallowed (debug log only).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger("apex7.external")

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_SERIES = {
    "US10Y": "DGS10",
    "CPI": "CPIAUCSL",
    "UNRATE": "UNRATE",
    "GDP_GROWTH": "A191RL1Q225SBEA",
    "FED_RATE": "FEDFUNDS",
}

_FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

_MACRO_INDICATORS_CACHE_SEC = 3600
_FRED_SERIES_CACHE_SEC = 3600
_FEAR_GREED_CACHE_SEC = 3600

_macro_indicators_cache: dict[str, Any] = {"data": None, "ts": 0.0}
_macro_indicators_lock = threading.Lock()

_fred_series_cache: dict[str, dict[str, Any]] = {}
_fred_series_lock = threading.Lock()

_fear_greed_cache: dict[str, Any] = {"data": None, "ts": 0.0}
_fear_greed_lock = threading.Lock()


def _fred_api_key(explicit: str) -> str:
    if explicit:
        return explicit.strip()
    from config import FRED_API_KEY

    return (FRED_API_KEY or "").strip()


def _parse_fred_observation_value(raw: str | None) -> float | None:
    """Return a float or None when FRED uses ``.`` / empty for missing."""
    if raw is None or raw in (".", ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _http_get_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    """GET and parse JSON; raises on HTTP error or invalid JSON."""
    with httpx.Client(timeout=10.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


def fetch_fred_latest(series_id: str, api_key: str = "") -> dict[str, Any] | None:
    """Fetch the latest observation for one FRED series.

    Free tier: ``api_key`` optional for many JSON requests; set ``FRED_API_KEY``
    in the environment for reliable access and higher limits.

    Returns:
        ``{"value": float, "date": "YYYY-MM-DD"}`` or ``None`` on failure /
        missing value.
    """
    key = _fred_api_key(api_key)
    now = time.time()
    with _fred_series_lock:
        cached = _fred_series_cache.get(series_id)
        if cached is not None and (now - cached["ts"]) < _FRED_SERIES_CACHE_SEC:
            return cached["data"]

    url = f"{_FRED_BASE}?series_id={series_id}&sort_order=desc&limit=1&file_type=json"
    if key:
        url += f"&api_key={key}"

    payload: dict[str, Any] | None = None
    try:
        data = _http_get_json(url)
        observations = data.get("observations") or []
        if not observations:
            payload = None
        else:
            row = observations[0]
            val = _parse_fred_observation_value(row.get("value"))
            if val is None:
                payload = None
            else:
                payload = {"value": val, "date": str(row.get("date", ""))}
    except Exception:
        logger.debug("FRED fetch failed for %s", series_id, exc_info=False)
        payload = None

    with _fred_series_lock:
        _fred_series_cache[series_id] = {"data": payload, "ts": time.time()}
    return payload


def fetch_macro_indicators() -> dict[str, dict[str, Any] | None]:
    """Fetch all configured FRED macro indicators.

    Cached 1 hour as a single bundle (same TTL as per-series cache entries).
    """
    with _macro_indicators_lock:
        now = time.time()
        if (
            _macro_indicators_cache["data"] is not None
            and (now - _macro_indicators_cache["ts"]) < _MACRO_INDICATORS_CACHE_SEC
        ):
            return _macro_indicators_cache["data"]

    key = _fred_api_key("")
    out: dict[str, dict[str, Any] | None] = {
        name: fetch_fred_latest(sid, api_key=key) for name, sid in _FRED_SERIES.items()
    }

    with _macro_indicators_lock:
        _macro_indicators_cache["data"] = out
        _macro_indicators_cache["ts"] = time.time()
    return out


def fetch_fear_greed() -> dict[str, Any] | None:
    """Fetch the CNN Fear & Greed Index.

    Returns:
        ``{"score": int 0–100, "label": str}`` or ``None`` on failure.
    """
    with _fear_greed_lock:
        now = time.time()
        if (
            _fear_greed_cache["data"] is not None
            and (now - _fear_greed_cache["ts"]) < _FEAR_GREED_CACHE_SEC
        ):
            return _fear_greed_cache["data"]

    payload: dict[str, Any] | None = None
    try:
        data = _http_get_json(
            _FNG_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        block = data.get("fear_and_greed") or {}
        score = block.get("score")
        label = block.get("rating")
        if score is not None:
            payload = {
                "score": int(round(float(score))),
                "label": str(label or "Unknown"),
            }
    except Exception:
        logger.debug("Fear & Greed fetch failed", exc_info=False)
        payload = None

    with _fear_greed_lock:
        _fear_greed_cache["data"] = payload
        _fear_greed_cache["ts"] = time.time()
    return payload
