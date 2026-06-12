"""APEX-7 // SURVIVAL TRADER — Dash app instance, design tokens, index_string."""

import hmac
import secrets
import time
from pathlib import Path

import dash
from flask import redirect, request, session

from config import DASHBOARD_SECRET_KEY, DEATH_THRESHOLD, INITIAL_BALANCE  # noqa: F401

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

# ═══════════════════════════════════════════════════════════════════════════════
# OPTIONAL AUTH GATE
# ═══════════════════════════════════════════════════════════════════════════════
# Enabled by setting DASHBOARD_PASSWORD in the environment; without it the
# dashboard stays open (default localhost usage). The signed session cookie
# needs a secret key: DASHBOARD_SECRET_KEY keeps sessions valid across
# restarts, otherwise a random per-process key is generated.

server.secret_key = DASHBOARD_SECRET_KEY or secrets.token_hex(32)

_AUTH_EXEMPT_PATHS = {"/login", "/logout", "/health", "/favicon.ico", "/_favicon.ico"}

_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>APEX-7 // LOGIN</title>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
  <style>
    body { background: #05090f; color: #b8d0d6; font-family: 'JetBrains Mono', monospace;
           display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
    .box { background: #070e16; border: 1px solid #0d2030; border-top: 2px solid #00dda0;
           border-radius: 4px; padding: 28px 32px; width: 300px; }
    h1 { font-size: 13px; letter-spacing: 0.18em; color: #00dda0; margin: 0 0 18px; }
    input { width: 100%; box-sizing: border-box; background: #040810; color: #b8d0d6;
            border: 1px solid #0d2030; border-radius: 3px; padding: 9px 10px;
            font-family: inherit; font-size: 12px; margin-bottom: 12px; }
    button { width: 100%; background: #00dda011; color: #00dda0; border: 1px solid #00dda055;
             border-radius: 3px; padding: 9px; font-family: inherit; font-size: 11px;
             font-weight: 700; letter-spacing: 0.14em; cursor: pointer; }
    button:hover { background: #00dda022; }
    .err { color: #ff4060; font-size: 11px; margin-bottom: 12px; }
  </style>
</head>
<body>
  <form class="box" method="post" action="/login">
    <h1>APEX-7 // ACCESS</h1>
    {error_html}
    <input type="password" name="password" placeholder="password" autofocus autocomplete="current-password">
    <button type="submit">AUTHENTICATE</button>
  </form>
</body>
</html>"""


def _auth_enabled() -> bool:
    """Read the password at request time so env/test overrides take effect."""
    import config

    return bool(config.DASHBOARD_PASSWORD)


@server.before_request
def _require_auth():
    """Gate every route behind the login session when auth is enabled.

    ``/health`` stays open for monitoring probes. Unauthenticated GETs are
    redirected to the login page; non-GETs (Dash callback XHRs) get a 401 so
    the front-end fails loudly instead of following an HTML redirect.
    """
    if not _auth_enabled() or session.get("apex7_auth"):
        return None
    if request.path in _AUTH_EXEMPT_PATHS:
        return None
    if request.method == "GET":
        return redirect("/login")
    return {"error": "authentication required"}, 401


@server.route("/login", methods=["GET", "POST"])
def _login():
    import config

    if not config.DASHBOARD_PASSWORD or session.get("apex7_auth"):
        return redirect("/")
    error_html = ""
    status = 200
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if hmac.compare_digest(supplied, config.DASHBOARD_PASSWORD):
            session["apex7_auth"] = True
            return redirect("/")
        time.sleep(0.3)  # slow down brute-force attempts
        error_html = '<div class="err">Invalid password</div>'
        status = 401
    return _LOGIN_PAGE.replace("{error_html}", error_html), status


@server.route("/logout")
def _logout():
    session.pop("apex7_auth", None)
    return redirect("/login")


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
  <script>
  document.addEventListener('keydown', function(e) {
    var el = document.activeElement;
    if (el && el.id === 'cli-input' && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      try {
        window.dash_clientside.set_props('cli-keyboard-event', {data: {key: e.key, ts: Date.now()}});
      } catch(_) {}
    }
  });
  </script>
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
