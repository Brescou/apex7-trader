"""APEX-7 — Callback package. Importing this module registers all callbacks."""

from dashboard.callbacks import live
from dashboard.callbacks import analytics
from dashboard.callbacks import backtest_tab
from dashboard.callbacks import agents
from dashboard.callbacks import terminal

__all__ = ["live", "analytics", "backtest_tab", "agents", "terminal"]
