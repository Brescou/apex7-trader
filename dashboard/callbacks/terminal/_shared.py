"""APEX-7 — Shared constants for the terminal-tab callback modules."""

from dashboard.server import BLUE, GREEN, PURPLE, YELLOW

# Local token not in server.py
BG_PANEL = "#0d1424"

_MACRO_KEYS = {"VIX": "^VIX", "SPY": "SPY", "DXY": "DX-Y.NYB"}
_MACRO_BAR_EXTRA_CACHE_SEC = 60.0
_FEAR_GREED_GREEN_LIGHT = "#86efac"
_FEAR_GREED_GREEN_DARK = "#15803d"

# Dot color palette for symbol cards (by position)
_DOT_PALETTE = [YELLOW, BLUE, GREEN, PURPLE]
