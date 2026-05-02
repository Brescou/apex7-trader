"""Tests for ``agents.shared.watchlist`` — SQLite-backed dynamic watchlist."""

import os
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import WATCHLIST
from agents.shared.watchlist import (
    add_to_watchlist,
    get_watchlist,
    remove_from_watchlist,
)


def test_get_watchlist_seeded(tmp_db) -> None:
    """Fresh DB is populated with default tickers from config."""
    wl = get_watchlist()
    assert isinstance(wl, list)
    assert len(wl) >= 5
    assert "AAPL" in wl


@patch("agents.shared.watchlist.yf.Ticker")
def test_add_symbol(mock_ticker, tmp_db) -> None:
    """Add NVDA and persist a row in ``watchlist``."""
    mock_ticker.return_value.history.return_value = pd.DataFrame({"Close": [1.0, 1.1]})
    assert add_to_watchlist("NVDA", source="manual") is True
    assert "NVDA" in get_watchlist()
    with sqlite3.connect(str(tmp_db)) as con:
        row = con.execute(
            "SELECT symbol, source FROM watchlist WHERE symbol=?",
            ("NVDA",),
        ).fetchone()
    assert row is not None
    assert row[0] == "NVDA"


@patch("agents.shared.watchlist.yf.Ticker")
def test_add_invalid_symbol(mock_ticker, tmp_db) -> None:
    """Invalid ticker (no history) is rejected."""
    mock_ticker.return_value.history.return_value = MagicMock(empty=True)
    before = list(get_watchlist())
    assert add_to_watchlist("NOTREALXYZ") is False
    assert get_watchlist() == before


@patch("agents.shared.watchlist.yf.Ticker")
def test_add_max_symbols(mock_ticker, tmp_db) -> None:
    """Exactly 20 symbols in DB → 21st add is rejected."""
    mock_ticker.return_value.history.return_value = pd.DataFrame({"Close": [1.0]})
    with sqlite3.connect(str(tmp_db)) as con:
        con.execute("DELETE FROM watchlist")
        for index in range(20):
            con.execute(
                "INSERT INTO watchlist (symbol, added_at, source) VALUES (?,?,?)",
                (f"S{index:03d}", "2026-01-01T00:00:00+00:00", "test"),
            )
        con.commit()
    assert len(get_watchlist()) == 20
    assert add_to_watchlist("NVDA") is False


def test_remove_symbol(tmp_db) -> None:
    """Symbol removed from SQLite."""
    assert "AAPL" in get_watchlist()
    assert remove_from_watchlist("AAPL", open_symbols=frozenset()) is True
    assert "AAPL" not in get_watchlist()
    with sqlite3.connect(str(tmp_db)) as con:
        row = con.execute(
            "SELECT 1 FROM watchlist WHERE symbol=?",
            ("AAPL",),
        ).fetchone()
    assert row is None


def test_remove_with_open_position(tmp_db, portfolio) -> None:
    """Cannot remove a symbol while the portfolio holds it."""
    portfolio.positions["AAPL"] = {"shares": 1.0, "avg_price": 100.0}
    assert remove_from_watchlist("AAPL", open_symbols=frozenset({"AAPL"})) is False
    assert "AAPL" in get_watchlist()


def test_get_watchlist_fallback(tmp_db) -> None:
    """Empty table → ``get_watchlist`` mirrors ``config.WATCHLIST``."""
    with sqlite3.connect(str(tmp_db)) as con:
        con.execute("DELETE FROM watchlist")
        con.commit()
    assert get_watchlist() == list(WATCHLIST)


def test_add_idempotent(tmp_db) -> None:
    """Already-listed symbol returns success without duplicate INSERT."""
    add_to_watchlist("AAPL")
    count_before = len(get_watchlist())
    add_to_watchlist("AAPL")  # 2ème ajout du même symbol
    count_after = len(get_watchlist())
    assert count_after == count_before, "Duplicate symbol inserted"
