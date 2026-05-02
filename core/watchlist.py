"""Persisted application watchlist (SQLite, mode-aware DB path)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import FrozenSet

import yfinance as yf

from config import WATCHLIST as DEFAULT_WATCHLIST

logger = logging.getLogger("apex7")

MAX_WATCHLIST_SYMBOLS = 20


def get_watchlist() -> list[str]:
    """Return symbols from the DB, ordered by ``added_at``. Fallback if empty."""
    from agents.shared.db import _db_read

    rows = _db_read("SELECT symbol FROM watchlist ORDER BY added_at ASC, symbol ASC")
    if not rows:
        return list(DEFAULT_WATCHLIST)
    return [str(r[0]) for r in rows]


def add_to_watchlist(symbol: str, source: str = "manual") -> bool:
    """Add a symbol after yfinance validation. Idempotent if already present. Max 20 symbols."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return False

    current = get_watchlist()
    if sym in current:
        return True
    if len(current) >= MAX_WATCHLIST_SYMBOLS:
        logger.warning("watchlist full (%d) — rejected %s", MAX_WATCHLIST_SYMBOLS, sym)
        return False

    try:
        hist = yf.Ticker(sym).history(period="5d", interval="1d")
        if hist.empty:
            logger.warning("watchlist add: no yfinance history for %s", sym)
            return False
    except Exception as exc:
        logger.warning("watchlist add: yfinance failed for %s: %s", sym, exc)
        return False

    from agents.shared.db import _db_write

    src = (source or "manual")[:64]
    ts = datetime.now(timezone.utc).isoformat()
    return _db_write(
        "INSERT INTO watchlist (symbol, added_at, source) VALUES (?,?,?)",
        (sym, ts, src),
    )


def remove_from_watchlist(
    symbol: str,
    *,
    open_symbols: FrozenSet[str] | None = None,
) -> bool:
    """Remove a symbol. Fails when ``symbol`` is in ``open_symbols`` (open position)."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return False
    if open_symbols is not None and sym in open_symbols:
        logger.info("watchlist remove blocked: open position on %s", sym)
        return False

    from agents.shared.db import _db_write

    return _db_write("DELETE FROM watchlist WHERE symbol=?", (sym,))
