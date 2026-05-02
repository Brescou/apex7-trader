"""APEX-7 // SURVIVAL TRADER — Dash app instance, design tokens, index_string."""

from pathlib import Path

import dash
from config import DEATH_THRESHOLD, INITIAL_BALANCE  # noqa: F401

# ═══════════════════════════════════════════════════════════════════════════════
# DESIGN TOKENS  (Apex7.html reference palette)
# ═══════════════════════════════════════════════════════════════════════════════

BG_BASE = "#05090f"  # page background
BG_NAV = "#060c13"  # top nav
BG_DEEP = "#040810"  # terminal / darkest areas
BG_CARD = "#070e16"  # card backgrounds
BG_HOVER = "#081420"  # hover state
BG_SELECTED = "#07121e"  # selected card

GREEN = "#00dda0"  # positive / buy / active
RED = "#ff4060"  # negative / sell / danger
ORANGE = "#e08030"  # warning / simulation
BLUE = "#3090ff"  # tactical / info
PURPLE = "#9070d0"  # supervisor
CYAN = "#28b0b0"  # system messages

BORDER = "#0d2030"  # default border
BORDER_INNER = "#091c28"  # inner dividers
BORDER_FAINT = "#070e16"  # faintest row borders

TEXT_MAIN = "#b8d0d6"  # high-emphasis
TEXT_DIM = "#6a9aaa"  # medium labels
TEXT_MUTED = "#3a6878"  # dim text
TEXT_FAINT = "#2e5060"  # inactive
TEXT_GHOST = "#1e3a4a"  # barely visible

# Legacy aliases kept for backward compat with existing callbacks
GRAY = TEXT_FAINT
YELLOW = "#d8b860"

FONT = "'JetBrains Mono', 'Fira Code', Consolas, monospace"

DB_PATH = Path(__file__).parent.parent / "trades.db"


def _rgba(hex_color: str, alpha: float) -> str:
    """Convert a 6-digit hex design token to an rgba() string for Plotly."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ═══════════════════════════════════════════════════════════════════════════════
# DASH APP INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

app = dash.Dash(
    __name__,
    title="APEX-7 // SURVIVAL TRADER",
    suppress_callback_exceptions=True,
    external_stylesheets=[
        "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap"
    ],
)
server = app.server

app.index_string = """<!DOCTYPE html>
<html lang="en">
<head>
  {%metas%}
  <title>{%title%}</title>
  {%favicon%}
  {%css%}
</head>
<body>
  {%app_entry%}
  <footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""


@server.route("/health")
def _health():
    """Health check endpoint for monitoring."""
    from agents.shared.nodes import get_runtime_mode, get_simulation_mode
    from dashboard.controller import _controller_lock, _ctrl, _state

    with _controller_lock:
        portfolio = _state.get("portfolio")
        cycle = _ctrl.get("cycle", 0)
        consecutive_holds = _state.get("consecutive_holds", 0)
    mode = get_runtime_mode()
    sim = get_simulation_mode()
    alive = not portfolio.is_dead if portfolio else False
    body = {
        "status": "ok" if alive else "dead",
        "agent_alive": alive,
        "cycle": cycle,
        "mode": mode,
        "simulation": sim,
        "consecutive_holds": consecutive_holds,
    }
    return body, (200 if alive else 503)
