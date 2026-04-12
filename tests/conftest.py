"""Shared pytest fixtures for APEX-7 tests."""

import os
import sqlite3

import pytest


@pytest.fixture(autouse=True)
def sim_mode():
    """Force simulation mode and disable portfolio saves for all tests.

    Sets env vars *before* any APEX-7 module is imported, then also
    toggles the runtime ``_sim_mode`` dict that nodes.py uses for
    hot-switching.
    """
    os.environ["SIMULATION_MODE"] = "true"
    os.environ["PORTFOLIO_SAVE_ENABLED"] = "false"
    os.environ["USE_LIVEFEED"] = "false"

    try:
        from agents.shared.nodes import _sim_mode

        _sim_mode["enabled"] = True
    except ImportError:
        pass

    yield

    try:
        from agents.shared.nodes import _sim_mode

        _sim_mode["enabled"] = True
    except ImportError:
        pass

    os.environ.pop("SIMULATION_MODE", None)
    os.environ.pop("PORTFOLIO_SAVE_ENABLED", None)
    os.environ.pop("USE_LIVEFEED", None)


@pytest.fixture
def portfolio():
    """Create a fresh Portfolio instance."""
    from core.data import Portfolio

    return Portfolio()


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database with the APEX-7 schema."""
    db_path = tmp_path / "test_trades.db"
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, symbol TEXT, action TEXT,
            price REAL, amount_usd REAL, shares REAL,
            reasoning TEXT, confidence REAL, emotion TEXT,
            portfolio_value_after REAL, lesson TEXT,
            source TEXT DEFAULT 'live'
        );
        CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, pattern TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, agent_name TEXT, symbol TEXT,
            vote TEXT, confidence REAL, was_correct INTEGER,
            lesson TEXT, source TEXT DEFAULT 'simulation'
        );
        CREATE TABLE IF NOT EXISTS postmortem (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, symbol TEXT, buy_price REAL,
            sell_price REAL, pnl_pct REAL, holding_hours REAL,
            agents_correct TEXT, summary TEXT,
            source TEXT DEFAULT 'simulation'
        );
        """
    )
    con.close()
    yield db_path
