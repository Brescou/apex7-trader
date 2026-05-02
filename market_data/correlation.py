"""Matrice de corrélation des rendements quotidiens."""

import logging
import time
from typing import Any

import pandas as pd

from market_data.caches import CORR_MATRIX_CACHE_SEC, _corr_matrix_cache, _corr_matrix_lock
from market_data.compat import yf

logger = logging.getLogger("apex7.market_data")


def fetch_correlation_matrix(symbols: list[str], period: str = "3mo") -> dict[str, Any]:
    """Daily return correlation matrix between tickers (Pearson on ``pct_change()``).

    Up to 10 symbols. Cached 5 minutes per (sorted symbols set, period).
    """
    syms = [str(s).strip().upper() for s in symbols if s and str(s).strip()][:10]
    if not syms:
        return {"symbols": [], "matrix": []}
    if len(syms) == 1:
        return {"symbols": syms, "matrix": [[1.0]]}

    cache_key = f"{period}|" + ",".join(sorted(syms))
    with _corr_matrix_lock:
        now = time.time()
        cached = _corr_matrix_cache.get("data")
        if (
            cached is not None
            and _corr_matrix_cache.get("key") == cache_key
            and (now - float(_corr_matrix_cache.get("ts") or 0)) < CORR_MATRIX_CACHE_SEC
        ):
            c = cached
            return {"symbols": list(c["symbols"]), "matrix": [list(r) for r in c["matrix"]]}

    try:
        df = yf.download(
            syms,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        if df is None or df.empty or len(df) < 5:
            out = {"symbols": syms, "matrix": []}
            with _corr_matrix_lock:
                _corr_matrix_cache["data"] = out
                _corr_matrix_cache["key"] = cache_key
                _corr_matrix_cache["ts"] = time.time()
            return {"symbols": list(out["symbols"]), "matrix": [list(r) for r in out["matrix"]]}

        if isinstance(df.columns, pd.MultiIndex) and "Close" in df.columns.get_level_values(0):
            closes = df["Close"].copy()
        else:
            out = {"symbols": syms, "matrix": []}
            with _corr_matrix_lock:
                _corr_matrix_cache["data"] = out
                _corr_matrix_cache["key"] = cache_key
                _corr_matrix_cache["ts"] = time.time()
            return {"symbols": list(out["symbols"]), "matrix": [list(r) for r in out["matrix"]]}

        present = [s for s in syms if s in closes.columns]
        if len(present) < 2:
            out = {"symbols": syms, "matrix": []}
            with _corr_matrix_lock:
                _corr_matrix_cache["data"] = out
                _corr_matrix_cache["key"] = cache_key
                _corr_matrix_cache["ts"] = time.time()
            return {"symbols": list(out["symbols"]), "matrix": [list(r) for r in out["matrix"]]}

        sub = closes[present]
        returns = sub.pct_change().dropna()
        if len(returns) < 5:
            out = {"symbols": present, "matrix": []}
            with _corr_matrix_lock:
                _corr_matrix_cache["data"] = out
                _corr_matrix_cache["key"] = cache_key
                _corr_matrix_cache["ts"] = time.time()
            return {"symbols": list(out["symbols"]), "matrix": [list(r) for r in out["matrix"]]}

        corr = returns.corr()
        order = [s for s in syms if s in corr.columns]
        subm = corr.loc[order, order]
        mat = [
            [round(float(x), 4) if pd.notna(x) else 0.0 for x in row]
            for row in subm.values.tolist()
        ]
        out = {"symbols": order, "matrix": mat}
    except Exception:
        logger.debug("Correlation matrix failed", exc_info=False)
        out = {"symbols": syms, "matrix": []}

    with _corr_matrix_lock:
        _corr_matrix_cache["data"] = out
        _corr_matrix_cache["key"] = cache_key
        _corr_matrix_cache["ts"] = time.time()
    return {"symbols": list(out["symbols"]), "matrix": [list(r) for r in out["matrix"]]}
