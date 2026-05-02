"""APEX-7 — Main layout assembly with DMC v2 MantineProvider."""

from __future__ import annotations

import dash_mantine_components as dmc
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
    ORANGE,
    TEXT_FAINT,
    TEXT_GHOST,
    TEXT_MAIN,
    app,
)

_NAV_H = "30px"

_MANTINE_THEME = {
    "fontFamily": FONT,
    "defaultRadius": 0,
    "primaryColor": "teal",
    "colors": {
        "teal": [
            "#e6fcf5",
            "#c3fae8",
            "#96f2d7",
            "#63e6be",
            "#38d9a9",
            "#20c997",
            "#12b886",
            "#0ca678",
            "#099268",
            "#00dda0",
        ]
    },
}


def setup_layout() -> None:
    """Assign app.layout."""
    _wl_startup = get_watchlist()
    app.layout = dmc.MantineProvider(
        theme=_MANTINE_THEME,
        forceColorScheme="dark",
        children=[
            html.Div(
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
                    # ── Stores & Intervals ───────────────────────────────────
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
                    dcc.Store(id="cli-history-pos", data=-1),
                    dcc.Store(id="cli-keyboard-event", data=None),
                    dcc.Interval(id="check-alerts-interval", interval=10000, n_intervals=0),
                    dcc.Interval(id="sector-heatmap-interval", interval=300000, n_intervals=0),
                    # ── TOP NAV BAR (30px) ──────────────────────────────────
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
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "gap": "0",
                                    "flexShrink": "0",
                                },
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
                                        style={"fontSize": "8px", "color": TEXT_GHOST},
                                    ),
                                ],
                                style={
                                    "border": f"1px solid {BORDER_INNER}",
                                    "padding": "1px 5px",
                                    "marginLeft": "8px",
                                    "letterSpacing": "0.12em",
                                    "flexShrink": "0",
                                },
                            ),
                            # Status dot
                            html.Div(
                                id="status-dot",
                                className="dot dot-alive",
                                style={"marginLeft": "10px", "flexShrink": "0"},
                            ),
                            # Banners
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
                            # ── DMC Tabs for routing ─────────────────────────
                            dmc.Tabs(
                                id="main-tabs",
                                value="live",
                                children=[
                                    dmc.TabsList(
                                        [
                                            dmc.TabsTab("LIVE", value="live"),
                                            dmc.TabsTab("ANALYTICS", value="analytics"),
                                            dmc.TabsTab("BACKTEST", value="backtest"),
                                            dmc.TabsTab("TERMINAL", value="terminal"),
                                        ],
                                    ),
                                ],
                                style={
                                    "flex": "1",
                                    "height": "100%",
                                    "marginLeft": "18px",
                                },
                            ),
                            # ── Right controls ───────────────────────────────
                            html.Div(
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "gap": "5px",
                                    "marginLeft": "auto",
                                    "flexShrink": "0",
                                },
                                children=[
                                    html.Div(id="mode-badge"),
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
                                        style={
                                            "width": "1px",
                                            "height": "12px",
                                            "background": BORDER_INNER,
                                        }
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
                    # ── TAB CONTENT (show/hide via _show_tab callback) ────────
                    html.Div(
                        id="tab-live",
                        children=_tab_live(),
                        style={
                            "flex": "1",
                            "minHeight": "0",
                            "overflow": "hidden",
                            "display": "block",
                        },
                    ),
                    html.Div(
                        id="tab-analytics",
                        children=_tab_analytics(),
                        style={
                            "flex": "1",
                            "minHeight": "0",
                            "overflow": "hidden",
                            "display": "none",
                        },
                    ),
                    html.Div(
                        id="tab-backtest",
                        children=_tab_backtest(),
                        style={
                            "flex": "1",
                            "minHeight": "0",
                            "overflow": "hidden",
                            "display": "none",
                        },
                    ),
                    html.Div(
                        id="tab-terminal",
                        children=_tab_terminal(),
                        style={
                            "flex": "1",
                            "minHeight": "0",
                            "overflow": "hidden",
                            "display": "none",
                        },
                    ),
                ],
            )
        ],
    )
