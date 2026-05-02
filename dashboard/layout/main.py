"""APEX-7 — Main layout assembly (app.layout assignment)."""

from dash import dcc, html

from agents.shared.nodes import get_runtime_mode
from dashboard.layout.analytics_tab import (
    _tab_agents,
    _tab_analytics,
    _tab_backtest,
)
from dashboard.layout.live_tab import _tab_live
from dashboard.layout.terminal_tab import _tab_terminal
from dashboard.server import (
    BG_CARD,
    BG_DEEP,
    BLUE,
    BORDER,
    FONT,
    GRAY,
    GREEN,
    TEXT_DIM,
    WATCHLIST,
    app,
)


def setup_layout() -> None:
    """Assign app.layout with all stores, intervals, top bar, tabs, and tab content."""
    app.layout = html.Div(
        id="page-bg",
        style={
            "background": BG_DEEP,
            "height": "100vh",
            "display": "flex",
            "flexDirection": "column",
            "fontFamily": FONT,
            "overflow": "hidden",
        },
        children=[
            dcc.Store(id="ctrl-store", data={"paused": False}),
            dcc.Store(id="mode-store", data={"mode": get_runtime_mode()}),
            dcc.Store(
                id="agent-cards-state",
                data={"tech": False, "analyst": False, "risk": False, "macro": False},
            ),
            dcc.Interval(id="tick", interval=2000, n_intervals=0),
            dcc.Interval(id="analytics-tick", interval=30000, n_intervals=0),
            dcc.Interval(id="agents-tick", interval=60000, n_intervals=0),
            dcc.Interval(id="macro-interval", interval=60000, n_intervals=0),
            dcc.Interval(id="watchlist-interval", interval=10000, n_intervals=0),
            dcc.Interval(id="news-interval", interval=120000, n_intervals=0),
            dcc.Store(id="terminal-watchlist", data=list(WATCHLIST)),
            dcc.Store(id="terminal-active-symbol", data=WATCHLIST[0] if WATCHLIST else "AAPL"),
            dcc.Store(id="price-alerts-store", data=[]),
            dcc.Store(id="screener-results-store", data=[]),
            dcc.Store(id="screener-active-store", data=False),
            dcc.Interval(id="check-alerts-interval", interval=10000, n_intervals=0),
            # ── TOP BAR (48px) ───────────────────────────────────────────────
            html.Div(
                id="top-bar",
                children=[
                    html.Div(
                        [
                            html.Div(id="status-dot", className="dot dot-alive"),
                            html.Div(
                                id="llm-degradation-banner",
                                style={"minWidth": "0", "maxWidth": "320px", "overflow": "hidden"},
                            ),
                            html.Div(
                                id="agent-error-banner",
                                style={"minWidth": "0", "maxWidth": "280px", "overflow": "hidden"},
                            ),
                            html.Div(
                                [
                                    html.Span(
                                        "APEX-7 // SURVIVAL TRADER",
                                        style={
                                            "color": TEXT_DIM,
                                            "fontSize": "12px",
                                            "fontWeight": "600",
                                            "letterSpacing": "0.18em",
                                        },
                                    ),
                                ]
                            ),
                            html.Div(
                                [
                                    html.Span(
                                        "ROUND ",
                                        style={
                                            "fontSize": "9px",
                                            "color": TEXT_DIM,
                                            "letterSpacing": "0.15em",
                                        },
                                    ),
                                    html.Span(
                                        id="round-num",
                                        children="—",
                                        style={"fontSize": "10px", "color": TEXT_DIM},
                                    ),
                                ],
                                style={
                                    "marginLeft": "6px",
                                    "display": "flex",
                                    "alignItems": "center",
                                },
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center", "gap": "12px"},
                    ),
                    html.Div(id="mode-badge"),
                    html.Div(
                        [
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
                                style={
                                    "display": "flex",
                                    "gap": "8px",
                                    "alignItems": "center",
                                    "fontSize": "10px",
                                    "fontWeight": "700",
                                    "letterSpacing": "0.1em",
                                    "color": GRAY,
                                },
                                labelStyle={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "gap": "4px",
                                    "cursor": "pointer",
                                },
                            ),
                            html.Div(
                                style={
                                    "width": "1px",
                                    "height": "14px",
                                    "background": BORDER,
                                }
                            ),
                            html.Button(
                                "PAUSE",
                                id="btn-pause",
                                n_clicks=0,
                                className="cbtn cbtn-pause",
                            ),
                            html.Button(
                                "STEP", id="btn-step", n_clicks=0, className="cbtn cbtn-step"
                            ),
                            html.Button(
                                "RESET",
                                id="btn-reset",
                                n_clicks=0,
                                className="cbtn cbtn-reset",
                            ),
                        ],
                        style={"display": "flex", "gap": "7px", "alignItems": "center"},
                    ),
                ],
                style={
                    "height": "48px",
                    "flexShrink": "0",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "space-between",
                    "padding": "0 18px",
                    "borderBottom": f"1px solid {BORDER}",
                    "background": BG_CARD,
                },
            ),
            # ── TABS BAR (38px) ──────────────────────────────────────────────
            _tabs_bar(),
            # ── TAB CONTENT (static — all tabs in DOM, visibility toggled) ──
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
                id="tab-agents",
                children=_tab_agents(),
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


def _tab_style() -> dict:
    return {
        "color": TEXT_DIM,
        "fontSize": "11px",
        "letterSpacing": "0.15em",
        "fontFamily": FONT,
        "fontWeight": "700",
        "padding": "0 16px",
        "border": "none",
        "borderBottom": "2px solid transparent",
        "background": BG_CARD,
        "cursor": "pointer",
    }


def _tab_selected_style(color: str = GREEN) -> dict:
    return {
        "color": color,
        "fontSize": "11px",
        "letterSpacing": "0.15em",
        "fontFamily": FONT,
        "fontWeight": "700",
        "padding": "0 16px",
        "border": "none",
        "borderBottom": f"2px solid {color}",
        "background": BG_CARD,
        "cursor": "pointer",
    }


def _tabs_bar() -> dcc.Tabs:
    ts = _tab_style()
    ss = _tab_selected_style()
    return dcc.Tabs(
        id="main-tabs",
        value="live",
        children=[
            dcc.Tab(label="LIVE", value="live", style=ts, selected_style=ss),
            dcc.Tab(label="ANALYTICS", value="analytics", style=ts, selected_style=ss),
            dcc.Tab(label="BACKTEST", value="backtest", style=ts, selected_style=ss),
            dcc.Tab(label="AGENTS", value="agents", style=ts, selected_style=ss),
            dcc.Tab(
                label="TERMINAL",
                value="terminal",
                style=ts,
                selected_style=_tab_selected_style(BLUE),
            ),
        ],
        style={"height": "38px", "flexShrink": "0"},
        colors={"border": BORDER, "primary": GREEN, "background": BG_CARD},
    )
