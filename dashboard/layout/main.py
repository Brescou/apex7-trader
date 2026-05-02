"""APEX-7 — Main layout assembly (app.layout assignment)."""

from dash import dcc, html

from agents.shared.nodes import get_runtime_mode
from agents.shared.watchlist import get_watchlist
from dashboard.layout.analytics_tab import _tab_analytics, _tab_backtest
from dashboard.layout.live_tab import _tab_live
from dashboard.layout.terminal_tab import _tab_terminal
from dashboard.server import (
    BG_BASE,
    BG_NAV,
    BORDER,
    BORDER_INNER,
    FONT,
    GREEN,
    ORANGE,
    TEXT_FAINT,
    TEXT_GHOST,
    TEXT_MAIN,
    app,
)

# ── shared inline style helpers ──────────────────────────────────────────────

_NAV_H = "30px"
_TABS_H = "30px"

_TAB_BASE = {
    "position": "relative",
    "display": "flex",
    "alignItems": "center",
    "padding": "0 18px",
    "fontSize": "9px",
    "letterSpacing": "0.16em",
    "fontWeight": "600",
    "color": TEXT_FAINT,
    "cursor": "pointer",
    "border": "none",
    "borderBottom": "2px solid transparent",
    "background": "none",
    "fontFamily": FONT,
    "height": "100%",
    "transition": "color 0.12s",
    "whiteSpace": "nowrap",
}

_TAB_ACTIVE = {
    **_TAB_BASE,
    "color": TEXT_MAIN,
    "borderBottom": f"2px solid {GREEN}",
}


def setup_layout() -> None:
    """Assign app.layout."""
    _wl_startup = get_watchlist()
    app.layout = html.Div(
        id="page-bg",
        style={
            "background": BG_BASE,
            "height": "100vh",
            "display": "flex",
            "flexDirection": "column",
            "fontFamily": FONT,
            "overflow": "hidden",
            "color": TEXT_MAIN,
        },
        children=[
            # ── Stores & Intervals ───────────────────────────────────────────
            dcc.Store(id="ctrl-store", data={"paused": False}),
            dcc.Store(id="mode-store", data={"mode": get_runtime_mode()}),
            dcc.Store(
                id="agent-cards-state",
                data={"tech": False, "analyst": False, "risk": False, "macro": False},
            ),
            dcc.Interval(id="tick", interval=2000, n_intervals=0),
            dcc.Interval(id="analytics-tick", interval=30000, n_intervals=0),
            dcc.Interval(id="macro-interval", interval=60000, n_intervals=0),
            dcc.Interval(id="watchlist-interval", interval=10000, n_intervals=0),
            dcc.Interval(id="news-interval", interval=120000, n_intervals=0),
            dcc.Store(id="terminal-watchlist", data=list(_wl_startup)),
            dcc.Store(
                id="terminal-active-symbol",
                data=_wl_startup[0] if _wl_startup else "AAPL",
            ),
            dcc.Store(id="price-alerts-store", data=[]),
            dcc.Store(id="screener-results-store", data=[]),
            dcc.Store(id="screener-active-store", data=False),
            dcc.Store(id="cli-history-store", data=[]),
            dcc.Interval(id="check-alerts-interval", interval=10000, n_intervals=0),
            dcc.Interval(id="sector-heatmap-interval", interval=300000, n_intervals=0),
            # ── TOP NAV BAR (30px) ───────────────────────────────────────────
            html.Div(
                id="top-bar",
                style={
                    "height": _NAV_H,
                    "flexShrink": "0",
                    "display": "flex",
                    "alignItems": "center",
                    "background": BG_NAV,
                    "borderBottom": f"1px solid {BORDER}",
                    "padding": "0 10px",
                    "gap": "0",
                    "position": "relative",
                    "zIndex": "100",
                },
                children=[
                    # Brand
                    html.Div(
                        [
                            html.Span(
                                "APEX-7",
                                style={
                                    "fontSize": "10px",
                                    "fontWeight": "700",
                                    "letterSpacing": "0.14em",
                                    "color": TEXT_MAIN,
                                },
                            ),
                            html.Span(
                                " // ",
                                style={"color": TEXT_GHOST, "margin": "0 1px"},
                            ),
                            html.Span(
                                "SURVIVAL TRADER",
                                style={
                                    "fontSize": "10px",
                                    "fontWeight": "700",
                                    "letterSpacing": "0.14em",
                                    "color": TEXT_MAIN,
                                },
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center", "gap": "0"},
                    ),
                    # Session badge
                    html.Div(
                        [
                            html.Span(
                                "ROUND ",
                                style={
                                    "fontSize": "8px",
                                    "color": TEXT_GHOST,
                                    "letterSpacing": "0.12em",
                                },
                            ),
                            html.Span(
                                id="round-num",
                                children="—",
                                style={
                                    "fontSize": "8px",
                                    "color": TEXT_GHOST,
                                },
                            ),
                        ],
                        style={
                            "fontSize": "8px",
                            "color": TEXT_GHOST,
                            "border": f"1px solid {BORDER_INNER}",
                            "padding": "1px 5px",
                            "marginLeft": "8px",
                            "letterSpacing": "0.12em",
                        },
                    ),
                    # Status dot
                    html.Div(
                        id="status-dot",
                        className="dot dot-alive",
                        style={"marginLeft": "10px"},
                    ),
                    # Degradation / error banners
                    html.Div(
                        id="llm-degradation-banner",
                        style={
                            "minWidth": "0",
                            "maxWidth": "280px",
                            "overflow": "hidden",
                            "marginLeft": "6px",
                        },
                    ),
                    html.Div(
                        id="agent-error-banner",
                        style={
                            "minWidth": "0",
                            "maxWidth": "220px",
                            "overflow": "hidden",
                            "marginLeft": "4px",
                        },
                    ),
                    # Tab buttons (center)
                    html.Div(
                        id="nav-tabs-bar",
                        style={
                            "display": "flex",
                            "flex": "1",
                            "alignItems": "stretch",
                            "marginLeft": "18px",
                            "height": "100%",
                        },
                        children=[
                            html.Button(
                                "LIVE",
                                id="nav-tab-live",
                                n_clicks=0,
                                style=_TAB_ACTIVE,
                            ),
                            html.Button(
                                "ANALYTICS",
                                id="nav-tab-analytics",
                                n_clicks=0,
                                style=_TAB_BASE,
                            ),
                            html.Button(
                                "BACKTEST",
                                id="nav-tab-backtest",
                                n_clicks=0,
                                style=_TAB_BASE,
                            ),
                            html.Button(
                                "TERMINAL",
                                id="nav-tab-terminal",
                                n_clicks=0,
                                style=_TAB_BASE,
                            ),
                        ],
                    ),
                    # Right controls
                    html.Div(
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "gap": "5px",
                            "marginLeft": "auto",
                        },
                        children=[
                            # Mode badge
                            html.Div(id="mode-badge"),
                            # Hidden mode radio (kept for callbacks, not visible in nav)
                            dcc.RadioItems(
                                id="mode-radio",
                                options=[
                                    {"label": " LIVE", "value": "live"},
                                    {"label": " PAPER", "value": "paper"},
                                    {"label": " SIM", "value": "sim"},
                                ],
                                value=get_runtime_mode(),
                                inline=True,
                                className="mode-radio",
                                style={"display": "none"},
                            ),
                            # SIM toggle button
                            html.Button(
                                id="sim-toggle-btn",
                                n_clicks=0,
                                children=[
                                    html.Span(
                                        id="sim-led",
                                        style={
                                            "width": "5px",
                                            "height": "5px",
                                            "borderRadius": "50%",
                                            "background": ORANGE,
                                            "display": "inline-block",
                                            "marginRight": "4px",
                                        },
                                    ),
                                    html.Span(id="sim-label", children="● SIMULATION"),
                                ],
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "border": f"1px solid {BORDER}",
                                    "color": TEXT_FAINT,
                                    "background": "none",
                                    "fontFamily": FONT,
                                    "fontSize": "8px",
                                    "fontWeight": "700",
                                    "letterSpacing": "0.16em",
                                    "padding": "2px 9px",
                                    "cursor": "pointer",
                                    "transition": "all 0.2s",
                                },
                            ),
                            html.Div(
                                style={"width": "1px", "height": "12px", "background": BORDER_INNER}
                            ),
                            html.Button(
                                "PAUSE",
                                id="btn-pause",
                                n_clicks=0,
                                className="cbtn cbtn-pause",
                            ),
                            html.Button(
                                "STEP",
                                id="btn-step",
                                n_clicks=0,
                                className="cbtn cbtn-step",
                            ),
                            html.Button(
                                "RESET",
                                id="btn-reset",
                                n_clicks=0,
                                className="cbtn cbtn-reset",
                            ),
                        ],
                    ),
                ],
            ),
            # ── Hidden dcc.Tabs for routing (keeps existing callbacks) ───────
            dcc.Tabs(
                id="main-tabs",
                value="live",
                children=[
                    dcc.Tab(label="LIVE", value="live"),
                    dcc.Tab(label="ANALYTICS", value="analytics"),
                    dcc.Tab(label="BACKTEST", value="backtest"),
                    dcc.Tab(label="TERMINAL", value="terminal"),
                ],
                style={"display": "none"},
            ),
            # ── TAB CONTENT ──────────────────────────────────────────────────
            html.Div(
                id="tab-live",
                children=_tab_live(),
                style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "block"},
            ),
            html.Div(
                id="tab-analytics",
                children=_tab_analytics(),
                style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "none"},
            ),
            html.Div(
                id="tab-backtest",
                children=_tab_backtest(),
                style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "none"},
            ),
            html.Div(
                id="tab-terminal",
                children=_tab_terminal(),
                style={"flex": "1", "minHeight": "0", "overflow": "hidden", "display": "none"},
            ),
        ],
    )
