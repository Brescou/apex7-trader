"""Shared pytest fixtures for APEX-7 tests."""

import os

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
def tmp_db(tmp_path, monkeypatch):
    """Route SQLite to a temp file (no writes to project ``trades*.db``)."""
    import sqlite3

    db = tmp_path / "test.db"
    monkeypatch.setattr("agents.shared.nodes._get_db_path", lambda: str(db))

    from agents.shared.nodes import _SCHEMA

    with sqlite3.connect(db) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=5000")
        con.executescript(_SCHEMA)
        for stmt in (
            "ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'live'",
            "ALTER TABLE trades ADD COLUMN trace_id TEXT",
            "ALTER TABLE trades ADD COLUMN prompt_version TEXT",
        ):
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass
        con.commit()
    yield db
