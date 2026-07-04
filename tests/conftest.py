"""Shared pytest fixtures for APEX-7 tests."""

import os

import pytest


@pytest.fixture(autouse=True)
def sim_mode(monkeypatch):
    """Force simulation mode and disable portfolio saves for all tests.

    ``config.PORTFOLIO_SAVE_ENABLED`` is read into ``core.data`` as a module
    attribute at import time, which happens during pytest collection —
    *before* this fixture body runs. Setting the env var here is a no-op for
    that value, so it must be monkeypatched directly on the ``config``
    module (read dynamically by ``Portfolio.save_state``) to actually take
    effect. The runtime ``_sim_mode``/``_paper_mode`` dicts are also toggled
    directly since nodes.py hot-switches on them regardless of env vars.
    """
    import config

    monkeypatch.setattr(config, "PORTFOLIO_SAVE_ENABLED", False)
    os.environ["SIMULATION_MODE"] = "true"
    os.environ["USE_LIVEFEED"] = "false"

    from agents.shared.nodes import _paper_mode, _sim_mode

    _sim_mode["enabled"] = True
    _paper_mode["enabled"] = False

    yield

    _sim_mode["enabled"] = True
    _paper_mode["enabled"] = False

    os.environ.pop("SIMULATION_MODE", None)
    os.environ.pop("USE_LIVEFEED", None)


@pytest.fixture
def portfolio():
    """Create a fresh Portfolio instance."""
    from core.data import Portfolio

    return Portfolio()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Route SQLite to a temp file (no writes to project ``trades*.db``)."""
    db = tmp_path / "test.db"
    monkeypatch.setattr("agents.shared.db._get_db_path", lambda: db)

    import agents.shared.db as db_mod

    db_mod._db_initialized_paths.discard(str(db))
    db_mod._ensure_db()
    yield db
    db_mod._db_initialized_paths.discard(str(db))
