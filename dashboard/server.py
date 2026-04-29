"""APEX-7 // SURVIVAL TRADER — Dash app instance, design tokens, index_string."""

from pathlib import Path

import dash
from config import AGENT_GRAPH, DEATH_THRESHOLD, INITIAL_BALANCE, WATCHLIST  # noqa: F401

# ═══════════════════════════════════════════════════════════════════════════════
# DESIGN TOKENS
# ═══════════════════════════════════════════════════════════════════════════════

BG_DEEP = "#060810"
BG_CARD = "#0a0f1e"
BG_HOVER = "#0f1729"
GREEN = "#10b981"
RED = "#ef4444"
BLUE = "#3b82f6"
ORANGE = "#f97316"
YELLOW = "#f59e0b"
PURPLE = "#8b5cf6"
GRAY = "#475569"
BORDER = "#1a2535"
TEXT_DIM = "#64748b"
TEXT_MAIN = "#e2e8f0"
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

app = dash.Dash(__name__, title="APEX-7 // SURVIVAL TRADER", suppress_callback_exceptions=True)
server = app.server

app.index_string = """<!DOCTYPE html>
<html>
<head>
  {%metas%}
  <title>{%title%}</title>
  {%favicon%}
  {%css%}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,300;0,400;0,600;0,700;1,400&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
    html, body { height:100%; overflow:hidden; }
    body {
      background:#060810;
      font-family:'JetBrains Mono','Fira Code',Consolas,monospace;
      color:#e2e8f0;
      -webkit-font-smoothing:antialiased;
    }
    ::-webkit-scrollbar { width:3px; }
    ::-webkit-scrollbar-track { background:#0a0f1e; }
    ::-webkit-scrollbar-thumb { background:#1a2535; border-radius:2px; }

    #scanlines {
      position:fixed; inset:0; pointer-events:none; z-index:1;
      background:repeating-linear-gradient(
        0deg, transparent, transparent 2px,
        rgba(0,0,0,0.025) 2px, rgba(0,0,0,0.025) 4px
      );
    }

    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
    @keyframes glow-g { 0%,100%{box-shadow:0 0 4px #10b981,0 0 10px #10b981} 50%{box-shadow:0 0 8px #10b981,0 0 20px #10b981,0 0 30px #10b98133} }
    @keyframes glow-y { 0%,100%{box-shadow:0 0 4px #f59e0b,0 0 10px #f59e0b} 50%{box-shadow:0 0 8px #f59e0b,0 0 20px #f59e0b} }
    @keyframes glow-o { 0%,100%{box-shadow:0 0 4px #f97316,0 0 10px #f97316} 50%{box-shadow:0 0 8px #f97316,0 0 20px #f97316,0 0 28px #f9731633} }
    .dot-degraded { background:#f97316; animation:glow-o 1.1s ease-in-out infinite; }
    .dot-alive    { background:#10b981; animation:glow-g 2s ease-in-out infinite; }
    .dot-thinking { background:#f59e0b; animation:glow-y 0.8s ease-in-out infinite; }
    .dot-dead     { background:#ef4444; animation:glow-r 0.45s ease-in-out infinite; }

    @keyframes sim-blink { 0%,100%{opacity:1;box-shadow:0 0 6px #f97316} 50%{opacity:.55;box-shadow:0 0 14px #f97316} }
    .badge-sim { animation:sim-blink 1.1s ease-in-out infinite; }

    .mode-radio label { cursor:pointer; }
    .mode-radio input[type=radio] { display:none; }

    @keyframes flicker { 0%,100%{opacity:1} 30%{opacity:.8} 70%{opacity:.92} }
    .flicker { animation:flicker .9s ease-in-out infinite; }
    @keyframes skull-pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.05)} }
    .skull-pulse { animation:skull-pulse 1.8s ease-in-out infinite; }

    /* Tab underline style */
    .tab-active { border-bottom: 2px solid #10b981 !important; color: #10b981 !important; }

    /* Control buttons */
    .cbtn {
      background:transparent; cursor:pointer;
      font-family:'JetBrains Mono',monospace;
      font-size:11px; font-weight:700; letter-spacing:.12em;
      padding:5px 12px; border-radius:3px; text-transform:uppercase;
      transition:border-color .15s, color .15s;
    }
    .cbtn-pause       { border:1px solid #1a2535; color:#475569; }
    .cbtn-pause:hover { border-color:#ef4444; color:#ef4444; }
    .cbtn-pause.on    { border-color:#f59e0b; color:#f59e0b; }
    .cbtn-step        { border:1px solid #1a2535; color:#475569; }
    .cbtn-step:hover  { border-color:#3b82f6; color:#3b82f6; }
    .cbtn-reset       { border:1px solid #1a2535; color:#475569; }
    .cbtn-reset:hover { border-color:#475569; color:#e2e8f0; }

    /* Dropdown overrides */
    .Select-control { background:#0a0f1e !important; border-color:#1a2535 !important; }
    .Select-menu-outer { background:#0a0f1e !important; border-color:#1a2535 !important; }
    .Select-option { background:#0a0f1e !important; color:#e2e8f0 !important; }
    .Select-option:hover { background:#0f1729 !important; }
    .Select-value-label { color:#e2e8f0 !important; }
  </style>
</head>
<body>
  <div id="scanlines"></div>
  {%app_entry%}
  <footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""


@server.route("/health")
def _health():
    """Health check endpoint for monitoring."""
    from dashboard.controller import _controller_lock, _ctrl, _state

    with _controller_lock:
        portfolio = _state.get("portfolio")
        cycle = _ctrl.get("cycle", 0)
        sim = _ctrl.get("sim_mode", False)
        consecutive_holds = _state.get("consecutive_holds", 0)
    alive = not portfolio.is_dead if portfolio else False
    body = {
        "status": "ok" if alive else "dead",
        "agent_alive": alive,
        "cycle": cycle,
        "simulation": sim,
        "consecutive_holds": consecutive_holds,
    }
    return body, (200 if alive else 503)
