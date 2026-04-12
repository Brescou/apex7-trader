"""APEX-7 — Analytics-related tab layouts (analytics, backtest, leaderboard, heatmap, agents)."""

from dash import dcc, html

from dashboard.server import (
    BG_CARD,
    BG_DEEP,
    BORDER,
    FONT,
    GREEN,
    PURPLE,
    TEXT_DIM,
    TEXT_MAIN,
)


def _tab_analytics() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Button(
                        "⟳ REFRESH",
                        id="btn-analytics-refresh",
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": f"1px solid {BORDER}",
                            "color": TEXT_DIM,
                            "fontFamily": FONT,
                            "fontSize": "10px",
                            "letterSpacing": "0.12em",
                            "padding": "4px 12px",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                        },
                    ),
                ],
                style={"padding": "12px 16px", "borderBottom": f"1px solid {BORDER}"},
            ),
            html.Div(
                id="analytics-content",
                style={
                    "flex": "1",
                    "overflowY": "auto",
                    "padding": "16px",
                },
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
            "overflow": "hidden",
        },
    )


def _tab_backtest() -> html.Div:
    _input_style = {
        "background": BG_DEEP,
        "border": f"1px solid {BORDER}",
        "color": TEXT_MAIN,
        "fontFamily": FONT,
        "fontSize": "11px",
        "padding": "5px 9px",
        "borderRadius": "3px",
        "outline": "none",
        "width": "100px",
    }
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                "SYMBOL",
                                style={
                                    "fontSize": "9px",
                                    "color": TEXT_DIM,
                                    "letterSpacing": "0.1em",
                                    "marginBottom": "3px",
                                },
                            ),
                            dcc.Input(
                                id="backtest-symbol",
                                type="text",
                                placeholder="AAPL",
                                value="AAPL",
                                debounce=True,
                                style=_input_style,
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Div(
                                "PERIOD",
                                style={
                                    "fontSize": "9px",
                                    "color": TEXT_DIM,
                                    "letterSpacing": "0.1em",
                                    "marginBottom": "3px",
                                },
                            ),
                            dcc.Dropdown(
                                id="backtest-period",
                                options=[
                                    {"label": p, "value": p} for p in ["1mo", "3mo", "6mo", "1y"]
                                ],
                                value="6mo",
                                clearable=False,
                                style={
                                    "width": "100px",
                                    "background": BG_CARD,
                                    "color": TEXT_MAIN,
                                    "fontFamily": FONT,
                                    "fontSize": "11px",
                                },
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Div(
                                "STRATEGY",
                                style={
                                    "fontSize": "9px",
                                    "color": TEXT_DIM,
                                    "letterSpacing": "0.1em",
                                    "marginBottom": "3px",
                                },
                            ),
                            dcc.RadioItems(
                                id="backtest-strategy",
                                options=[
                                    {"label": " SIMPLE", "value": "simple"},
                                    {"label": " MULTI", "value": "multi"},
                                ],
                                value="simple",
                                inline=True,
                                style={
                                    "fontSize": "11px",
                                    "color": TEXT_MAIN,
                                    "display": "flex",
                                    "gap": "12px",
                                    "alignItems": "center",
                                },
                                labelStyle={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "gap": "4px",
                                    "cursor": "pointer",
                                },
                            ),
                        ]
                    ),
                    html.Button(
                        "▶ RUN BACKTEST",
                        id="btn-backtest-run",
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": f"1px solid {GREEN}",
                            "color": GREEN,
                            "fontFamily": FONT,
                            "fontSize": "10px",
                            "letterSpacing": "0.12em",
                            "padding": "6px 16px",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                            "alignSelf": "flex-end",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "gap": "16px",
                    "alignItems": "flex-end",
                    "padding": "12px 16px",
                    "borderBottom": f"1px solid {BORDER}",
                    "flexShrink": "0",
                },
            ),
            dcc.Loading(
                id="bt-loading",
                children=html.Div(id="bt-results", style={"padding": "16px", "overflowY": "auto"}),
                color=GREEN,
                style={"flex": "1"},
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
        },
    )


def _tab_heatmap() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Button(
                        "⟳ REFRESH",
                        id="btn-heatmap-refresh",
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": f"1px solid {BORDER}",
                            "color": TEXT_DIM,
                            "fontFamily": FONT,
                            "fontSize": "10px",
                            "letterSpacing": "0.12em",
                            "padding": "4px 12px",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                        },
                    ),
                    html.Span(
                        id="heatmap-updated",
                        style={
                            "fontSize": "9px",
                            "color": TEXT_DIM,
                            "marginLeft": "12px",
                            "letterSpacing": "0.08em",
                        },
                    ),
                ],
                style={"padding": "12px 16px", "borderBottom": f"1px solid {BORDER}"},
            ),
            html.Div(
                id="heatmap-content",
                style={
                    "flex": "1",
                    "overflowY": "auto",
                    "padding": "16px",
                },
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
            "overflow": "hidden",
        },
    )


def _tab_agents() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Button(
                        "⟳ REFRESH",
                        id="btn-agents-refresh",
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": f"1px solid {BORDER}",
                            "color": TEXT_DIM,
                            "fontFamily": FONT,
                            "fontSize": "10px",
                            "letterSpacing": "0.12em",
                            "padding": "4px 12px",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                        },
                    ),
                ],
                style={"padding": "12px 16px", "borderBottom": f"1px solid {BORDER}"},
            ),
            html.Div(
                id="agents-content",
                style={
                    "flex": "1",
                    "overflowY": "auto",
                    "padding": "16px",
                },
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
            "overflow": "hidden",
        },
    )


def _tab_leaderboard() -> html.Div:
    scenarios = ["Bull Market", "Bear Market", "High Volatility", "Flat Market"]
    return html.Div(
        [
            html.Div(
                [
                    dcc.Dropdown(
                        id="lb-scenario",
                        options=[{"label": s, "value": s} for s in scenarios],
                        value=scenarios[0],
                        clearable=False,
                        style={
                            "width": "200px",
                            "background": BG_CARD,
                            "color": TEXT_MAIN,
                            "fontFamily": FONT,
                            "fontSize": "11px",
                        },
                    ),
                    html.Button(
                        "⚡ RUN ALL AGENTS",
                        id="btn-lb-run",
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": f"1px solid {PURPLE}",
                            "color": PURPLE,
                            "fontFamily": FONT,
                            "fontSize": "10px",
                            "letterSpacing": "0.12em",
                            "padding": "6px 16px",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "gap": "10px",
                    "alignItems": "center",
                    "padding": "12px 16px",
                    "borderBottom": f"1px solid {BORDER}",
                },
            ),
            dcc.Loading(
                id="lb-loading",
                children=html.Div(id="lb-results", style={"padding": "16px", "overflowY": "auto"}),
                color=PURPLE,
                style={"flex": "1"},
            ),
        ],
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 96px)",
        },
    )
