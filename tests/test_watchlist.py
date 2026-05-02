"""Tests for ``core.watchlist`` — SQLite-backed dynamic watchlist."""

import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.watchlist import (
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


@patch("core.watchlist.yf.Ticker")
def test_add_rejects_invalid_symbol(mock_ticker, tmp_db) -> None:
    mock_ticker.return_value.history.return_value = MagicMock(empty=True)
    before = list(get_watchlist())
    assert add_to_watchlist("NOTREALXYZ") is False
    assert get_watchlist() == before


@patch("core.watchlist.yf.Ticker")
def test_add_accepts_valid_symbol(mock_ticker, tmp_db) -> None:
    mock_ticker.return_value.history.return_value = pd.DataFrame({"Close": [1.0, 1.1]})
    assert add_to_watchlist("NVDA", source="manual") is True
    assert "NVDA" in get_watchlist()


def test_remove_blocked_when_open_position(tmp_db, portfolio) -> None:
    portfolio.positions["AAPL"] = {"shares": 1.0, "avg_price": 100.0}
    assert remove_from_watchlist("AAPL", open_symbols=frozenset({"AAPL"})) is False
    assert "AAPL" in get_watchlist()


def test_remove_allowed_without_position(tmp_db) -> None:
    assert "AAPL" in get_watchlist()
    assert remove_from_watchlist("AAPL", open_symbols=frozenset()) is True
    assert "AAPL" not in get_watchlist()


def test_add_idempotent(tmp_db) -> None:
    wl = get_watchlist()
    sym = wl[0]
    assert add_to_watchlist(sym) is True


def test_max_watchlist_size(tmp_db, monkeypatch) -> None:
    monkeypatch.setattr("core.watchlist.MAX_WATCHLIST_SYMBOLS", 3)
    assert add_to_watchlist("ZZNEWTICK") is False
