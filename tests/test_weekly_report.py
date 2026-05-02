"""Tests for weekly Discord report scheduling (sim skip)."""

from unittest.mock import MagicMock, patch

from agents.multi import run_weekly_report
from agents.shared.modes import _sim_mode


def test_run_weekly_report_skips_in_simulation_mode() -> None:
    """No Discord call when simulation mode is enabled."""
    _sim_mode["enabled"] = True
    try:
        with patch("core.notifications.alert_weekly_report") as aw:
            run_weekly_report(MagicMock())
        aw.assert_not_called()
    finally:
        _sim_mode["enabled"] = False
