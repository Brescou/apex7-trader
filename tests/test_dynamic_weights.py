"""Tests for ``_compute_dynamic_weights`` graceful degradation + thread safety.

Covers Tâche 3.3 of Sprint Features v1:
- No evaluated history → pure static fallback.
- Below ``_MIN_EVALUATED_VOTES`` → static weight kept for that agent.
- Mixed (some agents evaluated, others pending) → blended weights, sum == 1.
- ``_weights_lock`` is held during cache check + DB read.
"""

import math
import os
import sqlite3
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import agents.multi as multi_mod
from agents.multi import WEIGHTS, _compute_dynamic_weights


@pytest.fixture
def fresh_cache():
    """Reset the module-level cache before each test."""
    multi_mod._cached_weights = {}
    multi_mod._weights_computed_at = 0.0
    yield
    multi_mod._cached_weights = {}
    multi_mod._weights_computed_at = 0.0


def _seed_votes(db_path, agent: str, results: list[int]) -> None:
    """Insert ``len(results)`` evaluated votes for ``agent``."""
    with sqlite3.connect(db_path) as con:
        for i, val in enumerate(results):
            con.execute(
                "INSERT INTO agent_memory "
                "(timestamp,agent_name,symbol,vote,confidence,was_correct,lesson,source) "
                "VALUES (?,?,?,?,?,?,?,'live')",
                (f"2026-04-{20 + i:02d}T12:00:00", agent, "AAPL", "BUY", 0.7, val, None),
            )


# ── Graceful degradation ────────────────────────────────────────────────────


def test_static_when_no_history(tmp_db, fresh_cache) -> None:
    """Empty ``agent_memory`` → static :data:`WEIGHTS`, sum == 1."""
    out = _compute_dynamic_weights()
    assert out == WEIGHTS
    assert math.isclose(sum(out.values()), 1.0, abs_tol=1e-9)


def test_static_when_below_threshold(tmp_db, fresh_cache) -> None:
    """A single agent with <5 evaluated votes still falls back to static."""
    _seed_votes(tmp_db, "technician", [1, 1, 0])  # only 3 evaluated
    out = _compute_dynamic_weights()
    assert out == WEIGHTS


def test_blend_when_some_agents_have_history(tmp_db, fresh_cache) -> None:
    """Mixed case: weights stay normalised; agents without history keep static base."""
    _seed_votes(tmp_db, "technician", [1, 1, 1, 1, 0])  # 80 % accuracy
    _seed_votes(tmp_db, "analyst", [1, 0, 1, 0, 1])  # 60 % accuracy
    out = _compute_dynamic_weights()
    assert set(out) == set(WEIGHTS)
    assert math.isclose(sum(out.values()), 1.0, abs_tol=1e-9)
    # Pending agents should still be present with non-zero weight.
    assert out["risk_manager"] > 0
    assert out["macro_watcher"] > 0


def test_logs_evaluated_and_pending(tmp_db, fresh_cache, caplog) -> None:
    """The function logs how many agents have evaluated history."""
    _seed_votes(tmp_db, "technician", [1, 1, 1, 1, 1])
    with caplog.at_level("INFO", logger="apex7.multi"):
        _compute_dynamic_weights()
    assert any(
        "agents have evaluated history" in rec.message for rec in caplog.records
    ), "Expected dynamic-weights summary log line"


# ── Thread safety ───────────────────────────────────────────────────────────


def test_concurrent_calls_are_serialised(tmp_db, fresh_cache) -> None:
    """``_weights_lock`` must serialise concurrent computations.

    We patch ``_db_read`` with a slow stub and fire 8 threads simultaneously;
    every thread must observe the same cached dict at the end.
    """
    import time

    call_count = {"n": 0}
    real_db_read = multi_mod._db_read

    def slow_db_read(*args, **kwargs):
        call_count["n"] += 1
        time.sleep(0.05)
        return real_db_read(*args, **kwargs)

    multi_mod._db_read = slow_db_read
    try:
        results: list[dict] = []
        threads = [
            threading.Thread(target=lambda: results.append(_compute_dynamic_weights()))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        multi_mod._db_read = real_db_read

    # All threads receive a consistent dict (same keys, same values).
    assert all(r == results[0] for r in results)
    # The cache prevents re-reading the DB more than once for the burst.
    # 8 threads × 4 agent reads would be 32 calls without the lock.
    assert call_count["n"] <= 4, f"DB hit too many times under concurrency: {call_count['n']}"
