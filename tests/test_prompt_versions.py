"""Tests for the A/B prompt-version stats (loader + analytics section)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _insert_trade(ts: str, action: str, trace_id: str, version: str) -> None:
    from agents.shared.db import _db_write

    _db_write(
        "INSERT INTO trades (timestamp, symbol, action, price, amount_usd, shares, "
        "confidence, trace_id, source, prompt_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (ts, "AAPL", action, 100.0, 100.0, 1.0, 0.8, trace_id, "live", version),
    )


def _insert_votes(trace_id: str, was_correct) -> None:
    """Four agent rows per trace, all sharing the same verdict (like eval.py)."""
    from agents.shared.db import _db_write

    for agent in ("technician", "analyst", "risk_manager", "macro_watcher"):
        _db_write(
            "INSERT INTO agent_memory (timestamp, agent_name, symbol, vote, "
            "confidence, was_correct, trace_id, source) VALUES (?,?,?,?,?,?,?,?)",
            ("2026-01-01T00:00:00", agent, "AAPL", "BUY", 0.7, was_correct, trace_id, "live"),
        )


def _seed_two_versions() -> None:
    # v1.0 — 3 trades: one correct, one wrong, one pending
    _insert_trade("2026-01-01T10:00:00", "BUY", "t1", "v1.0")
    _insert_votes("t1", 1)
    _insert_trade("2026-01-02T10:00:00", "SELL", "t2", "v1.0")
    _insert_votes("t2", 0)
    _insert_trade("2026-01-03T10:00:00", "BUY", "t3", "v1.0")
    _insert_votes("t3", None)
    # v1.1 — 2 trades: one correct, one pending
    _insert_trade("2026-02-01T10:00:00", "BUY", "t4", "v1.1")
    _insert_votes("t4", 1)
    _insert_trade("2026-02-02T10:00:00", "SELL", "t5", "v1.1")
    _insert_votes("t5", None)


def test_loader_groups_by_version(tmp_db):
    from dashboard.layout.loaders import _load_prompt_version_stats

    _seed_two_versions()
    stats = _load_prompt_version_stats()
    assert [s["version"] for s in stats] == ["v1.0", "v1.1"]  # chronological

    v10, v11 = stats
    assert v10["n_trades"] == 3 and v10["buys"] == 2 and v10["sells"] == 1
    assert v10["evaluated"] == 2 and v10["wins"] == 1
    assert v11["n_trades"] == 2
    assert v11["evaluated"] == 1 and v11["wins"] == 1


def test_loader_empty_db(tmp_db):
    from dashboard.layout.loaders import _load_prompt_version_stats

    assert _load_prompt_version_stats() == []


def test_loader_null_version_bucketed(tmp_db):
    from dashboard.layout.loaders import _load_prompt_version_stats

    _insert_trade("2026-01-01T10:00:00", "BUY", "t1", None)
    stats = _load_prompt_version_stats()
    assert len(stats) == 1
    assert stats[0]["version"] == "—"
    assert stats[0]["evaluated"] == 0


def _collect_text(component) -> str:
    """Flatten a Dash component tree into its concatenated text content."""
    parts: list[str] = []

    def walk(node):
        if node is None:
            return
        if isinstance(node, (str, int, float)):
            parts.append(str(node))
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child)
            return
        walk(getattr(node, "children", None))

    walk(component)
    return " ".join(parts)


def test_section_renders_cards_and_significance_warning(tmp_db):
    from dashboard.callbacks.analytics import _prompt_versions_section

    _seed_two_versions()
    section = _prompt_versions_section()
    text = _collect_text(section)
    assert "v1.0" in text and "v1.1" in text
    # both versions have far fewer than 30 evaluated trades
    assert "non significatif" in text


def test_section_single_version_shows_hint(tmp_db):
    from dashboard.callbacks.analytics import _prompt_versions_section

    _insert_trade("2026-01-01T10:00:00", "BUY", "t1", "v1.0")
    text = _collect_text(_prompt_versions_section())
    assert "PROMPT_VERSION" in text  # hint about bumping the version
