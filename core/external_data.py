"""External market data not sourced from yfinance (FRED, CNN Fear & Greed).

Thread-safe in-memory TTL caches; network errors are swallowed (debug log only).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date as _date
from typing import Any

import httpx

logger = logging.getLogger("apex7.external")

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_RELEASE_BASE = "https://api.stlouisfed.org/fred/release/dates"
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
# On a failed/empty fetch, retry this soon instead of waiting the full TTL —
# while still serving the last known-good cached value in the meantime
# (avoids caching None for a full hour on a transient timeout or a FRED
# holiday gap).
_NEGATIVE_CACHE_RETRY_SEC = 60

_macro_indicators_cache: dict[str, Any] = {"data": None, "ts": 0.0}
_macro_indicators_lock = threading.Lock()

_FRED_RELEASE_CACHE_SEC = 21600  # 6 hours — release schedules change rarely

_fred_series_cache: dict[str, dict[str, Any]] = {}
_fred_series_lock = threading.Lock()

_fred_release_cache: dict[int, dict[str, Any]] = {}
_fred_release_lock = threading.Lock()

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


def fetch_fred_latest(
    series_id: str,
    api_key: str = "",
    *,
    max_cache_sec: float | None = None,
) -> dict[str, Any] | None:
    """Fetch the latest observation for one FRED series.

    Free tier: ``api_key`` optional for many JSON requests; set ``FRED_API_KEY``
    in the environment for reliable access and higher limits.

    Args:
        series_id: FRED series id (e.g. ``DGS10``).
        api_key: Optional API key; defaults to env.
        max_cache_sec: If set, refresh when cache is older than this many seconds
            (defaults to ``_FRED_SERIES_CACHE_SEC``).

    Returns:
        ``{"value": float, "date": "YYYY-MM-DD"}`` or ``None`` on failure /
        missing value.
    """
    key = _fred_api_key(api_key)
    ttl = float(max_cache_sec) if max_cache_sec is not None else float(_FRED_SERIES_CACHE_SEC)
    now = time.time()
    with _fred_series_lock:
        cached = _fred_series_cache.get(series_id)
        if cached is not None:
            if (now - cached["ts"]) < ttl:
                return cached["data"]
            if (
                cached["data"] is not None
                and (now - cached.get("last_attempt", cached["ts"])) < _NEGATIVE_CACHE_RETRY_SEC
            ):
                # Stale but a fetch was already attempted very recently and
                # failed/came back empty — keep serving the last known-good
                # value instead of caching None for the full TTL.
                return cached["data"]

    # limit=5 (not 1): the most recent observation for a daily series like
    # DGS10 is frequently "." on market holidays / delayed releases — walk
    # back through recent observations for the first non-missing value
    # instead of treating a single missing tick as "no data".
    url = f"{_FRED_BASE}?series_id={series_id}&sort_order=desc&limit=5&file_type=json"
    if key:
        url += f"&api_key={key}"

    payload: dict[str, Any] | None = None
    try:
        data = _http_get_json(url)
        for row in data.get("observations") or []:
            val = _parse_fred_observation_value(row.get("value"))
            if val is not None:
                payload = {"value": val, "date": str(row.get("date", ""))}
                break
    except Exception:
        logger.debug("FRED fetch failed for %s", series_id, exc_info=False)
        payload = None

    with _fred_series_lock:
        now = time.time()
        if payload is not None:
            _fred_series_cache[series_id] = {"data": payload, "ts": now, "last_attempt": now}
            return payload
        prev = _fred_series_cache.get(series_id)
        if prev is not None and prev.get("data") is not None:
            _fred_series_cache[series_id] = {**prev, "last_attempt": now}
            return prev["data"]
        _fred_series_cache[series_id] = {"data": None, "ts": now, "last_attempt": now}
        return None


def fetch_fred_release_dates(
    release_id: int,
    api_key: str = "",
    *,
    limit: int = 24,
    max_cache_sec: float | None = None,
) -> list[str]:
    """Upcoming release dates for a FRED *release* (e.g. 10=CPI, 50=Employment).

    Returns a sorted list of ``YYYY-MM-DD`` strings from today onward (at most
    ``limit``), or ``[]`` on failure / no key. Cached 6 h. Used by the economic
    calendar to auto-refresh CPI/NFP dates instead of a hardcoded schedule.

    FRED's free tier serves many JSON requests without a key but is rate
    limited — set ``FRED_API_KEY`` for reliable access.
    """
    key = _fred_api_key(api_key)
    ttl = float(max_cache_sec) if max_cache_sec is not None else float(_FRED_RELEASE_CACHE_SEC)
    now = time.time()
    with _fred_release_lock:
        cached = _fred_release_cache.get(release_id)
        if cached is not None and (now - cached["ts"]) < ttl:
            return cached["data"]

    today = _date.today().isoformat()
    url = (
        f"{_FRED_RELEASE_BASE}?release_id={release_id}"
        "&include_release_dates_with_no_data=true&sort_order=asc&file_type=json"
        f"&realtime_start={today}&realtime_end=9999-12-31"
    )
    if key:
        url += f"&api_key={key}"

    out: list[str] = []
    try:
        data = _http_get_json(url)
        seen: set[str] = set()
        for row in data.get("release_dates") or []:
            d = str(row.get("date", ""))[:10]
            if d and d >= today and d not in seen:
                seen.add(d)
                out.append(d)
        out = sorted(out)[:limit]
    except Exception:
        logger.debug("FRED release dates fetch failed for %s", release_id, exc_info=False)
        out = []

    with _fred_release_lock:
        _fred_release_cache[release_id] = {"data": out, "ts": time.time()}
    return out


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


def fetch_fear_greed(*, max_cache_sec: float | None = None) -> dict[str, Any] | None:
    """Fetch the CNN Fear & Greed Index.

    Args:
        max_cache_sec: If set, refresh when cache is older than this many seconds
            (defaults to ``_FEAR_GREED_CACHE_SEC``).

    Returns:
        ``{"score": int 0–100, "label": str}`` or ``None`` on failure.
    """
    ttl = float(max_cache_sec) if max_cache_sec is not None else float(_FEAR_GREED_CACHE_SEC)
    with _fear_greed_lock:
        now = time.time()
        if _fear_greed_cache["data"] is not None and (now - _fear_greed_cache["ts"]) < ttl:
            return _fear_greed_cache["data"]
        if (
            _fear_greed_cache["data"] is not None
            and (now - _fear_greed_cache.get("last_attempt", _fear_greed_cache["ts"]))
            < _NEGATIVE_CACHE_RETRY_SEC
        ):
            # Stale but a fetch failed very recently — keep serving the last
            # known-good value instead of caching None for the full TTL on a
            # transient timeout/503.
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
        now = time.time()
        if payload is not None:
            _fear_greed_cache["data"] = payload
            _fear_greed_cache["ts"] = now
            _fear_greed_cache["last_attempt"] = now
        else:
            _fear_greed_cache["last_attempt"] = now
            if _fear_greed_cache["data"] is None:
                _fear_greed_cache["ts"] = now
            payload = _fear_greed_cache["data"]
    return payload
