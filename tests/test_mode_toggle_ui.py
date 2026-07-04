"""UI-side tests for the 3-mode toggle (Feature 4.2).

* ``_toggle_mode`` callback flips ``_sim_mode`` / ``_paper_mode`` correctly.
* ``_mode_palette`` returns distinct (label, color, css_class) per mode.
* ``/health`` exposes the active mode label.
* ``_classify_v2`` recognises ``[PAPER]`` log entries.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import agents.shared.nodes as nodes


@pytest.fixture(autouse=True)
def reset_modes(monkeypatch):
    monkeypatch.setattr(nodes, "_write_env_var", lambda *a, **kw: None)
    nodes._sim_mode["enabled"] = False
    nodes._paper_mode["enabled"] = False
    yield
    nodes._sim_mode["enabled"] = True
    nodes._paper_mode["enabled"] = False


# ── Toggle callback ─────────────────────────────────────────────────────────


def test_toggle_mode_to_paper() -> None:
    from dashboard.callbacks.live import _toggle_mode

    out = _toggle_mode("paper")
    assert out == {"mode": "paper"}
    assert nodes.get_paper_mode() is True
    assert nodes.get_simulation_mode() is False


def test_toggle_mode_to_sim() -> None:
    """Entering SIM crosses the fake-price boundary — _toggle_mode swaps in a
    fresh Portfolio and launches a new agent thread. _launch is mocked so
    this unit test doesn't spawn a real background thread for the rest of
    the pytest process.
    """
    from dashboard.callbacks.live import _toggle_mode

    with patch("dashboard.callbacks.live._launch") as mock_launch:
        out = _toggle_mode("sim")
    mock_launch.assert_called_once()
    assert out == {"mode": "sim"}
    assert nodes.get_simulation_mode() is True
    assert nodes.get_paper_mode() is False


def test_toggle_mode_to_live_clears_both() -> None:
    """Leaving SIM also crosses the boundary — same _launch mock needed."""
    from dashboard.callbacks.live import _toggle_mode

    nodes._sim_mode["enabled"] = True
    nodes._paper_mode["enabled"] = True  # defensive double-flag
    with patch("dashboard.callbacks.live._launch") as mock_launch:
        out = _toggle_mode("live")
    mock_launch.assert_called_once()
    assert out == {"mode": "live"}
    assert nodes.get_simulation_mode() is False
    assert nodes.get_paper_mode() is False


# ── Badge palette ───────────────────────────────────────────────────────────


def test_mode_palette_distinct_per_mode() -> None:
    from dashboard.callbacks.live import _mode_palette

    live_label, live_color, live_cls = _mode_palette("live")
    paper_label, paper_color, paper_cls = _mode_palette("paper")
    sim_label, sim_color, sim_cls = _mode_palette("sim")

    assert "LIVE" in live_label and live_cls == ""
    assert "PAPER" in paper_label and paper_cls == "badge-paper"
    assert "SIMULATION" in sim_label and sim_cls == "badge-sim"
    # Distinct colors for each mode.
    assert len({live_color, paper_color, sim_color}) == 3


# ── /health endpoint ────────────────────────────────────────────────────────


def test_health_endpoint_exposes_mode() -> None:
    from dashboard import create_app

    app = create_app()
    nodes._paper_mode["enabled"] = True
    with app.server.test_client() as client:
        resp = client.get("/health")
    payload = resp.get_json()
    assert payload is not None
    assert payload["mode"] == "paper"


# ── classify ─────────────────────────────────────────────────────────────────


def test_classify_recognises_paper_prefix() -> None:
    from dashboard.layout.classify import _classify_v2

    badge, _color = _classify_v2("[PAPER] BUY AAPL @ $150 — RSI signal", "info")
    assert badge == "PAPER"


def test_classify_paper_specialist_tags() -> None:
    from dashboard.layout.classify import _classify_v2

    assert _classify_v2("[PAPER][TECH] BUY AAPL", "info")[0] == "TECH"
    assert _classify_v2("[PAPER][ANLST] news ok", "info")[0] == "ANLST"
    assert _classify_v2("[PAPER][RISK] sizing FULL", "info")[0] == "RISK"
    assert _classify_v2("[PAPER][MACRO] risk-on", "info")[0] == "MACRO"
