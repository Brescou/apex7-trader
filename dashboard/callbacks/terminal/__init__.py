"""APEX-7 — Terminal tab callbacks.

Importing this package registers every terminal callback by importing the
three submodules (macro / watchlist / charts). The split keeps each file
focused; the original monolithic ``terminal.py`` lived here.
"""

from dashboard.callbacks.terminal import macro
from dashboard.callbacks.terminal import watchlist
from dashboard.callbacks.terminal import charts

__all__ = ["macro", "watchlist", "charts"]
