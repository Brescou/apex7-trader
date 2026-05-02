"""APEX-7 — Terminal tab layout skeleton."""

from dash import dcc, html

from core.watchlist import get_watchlist
from dashboard.layout.helpers import _section_label
from dashboard.server import (
    BG_CARD,
    BG_DEEP,
    BG_HOVER,
    BLUE,
    BORDER,
    FONT,
    GREEN,
    PURPLE,
    TEXT_DIM,
    TEXT_MAIN,
)


def _tab_terminal() -> html.Div:
    _wl_compare = get_watchlist()
    _input_style = {
        "background": BG_DEEP,
        "border": f"1px solid {BORDER}",
        "color": TEXT_MAIN,
        "fontFamily": FONT,
        "fontSize": "11px",
        "padding": "5px 9px",
        "borderRadius": "3px",
        "outline": "none",
        "width": "140px",
    }
    _btn_style = {
        "background": "transparent",
        "border": f"1px solid {GREEN}",
        "color": GREEN,
        "fontFamily": FONT,
        "fontSize": "10px",
        "letterSpacing": "0.1em",
        "padding": "5px 12px",
        "cursor": "pointer",
        "borderRadius": "3px",
        "flexShrink": "0",
    }
    _alert_input_style = {
        "background": BG_DEEP,
        "border": f"1px solid {BORDER}",
        "color": TEXT_MAIN,
        "fontFamily": FONT,
        "fontSize": "11px",
        "padding": "5px 9px",
        "borderRadius": "3px",
        "outline": "none",
        "width": "90px",
    }
    return html.Div(
        [
            # ── A) Macro Header Bar (64px, full width) ────────────────────────────
            html.Div(
                [
                    html.Div(
                        id="macro-bar-content",
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "gap": "0",
                            "flex": "1",
                        },
                    ),
                ],
                style={
                    "background": BG_HOVER,
                    "borderBottom": f"1px solid {BORDER}",
                    "padding": "0 18px",
                    "height": "64px",
                    "display": "flex",
                    "alignItems": "center",
                    "flexShrink": "0",
                },
            ),
            # ── B) 2-column layout (65% / 35%) ───────────────────────────────────
            html.Div(
                [
                    # Left column (65%)
                    html.Div(
                        [
                            # C) Watchlist header + ADD input + card grid
                            html.Div(
                                [
                                    _section_label("WATCHLIST"),
                                    html.Div(
                                        [
                                            dcc.Input(
                                                id="watchlist-add-input",
                                                placeholder="Symbol (e.g. NVDA)",
                                                debounce=False,
                                                style=_input_style,
                                            ),
                                            html.Button(
                                                "ADD",
                                                id="btn-watchlist-add",
                                                n_clicks=0,
                                                style=_btn_style,
                                            ),
                                            html.Button(
                                                "COMPARE",
                                                id="btn-compare",
                                                n_clicks=0,
                                                style={
                                                    "background": "transparent",
                                                    "border": f"1px solid {BLUE}",
                                                    "color": BLUE,
                                                    "fontFamily": FONT,
                                                    "fontSize": "10px",
                                                    "letterSpacing": "0.1em",
                                                    "padding": "5px 10px",
                                                    "cursor": "pointer",
                                                    "borderRadius": "3px",
                                                    "flexShrink": "0",
                                                },
                                            ),
                                            html.Button(
                                                "CSV",
                                                id="btn-export-csv",
                                                n_clicks=0,
                                                style={
                                                    "background": "transparent",
                                                    "border": f"1px solid {BORDER}",
                                                    "color": TEXT_DIM,
                                                    "fontFamily": FONT,
                                                    "fontSize": "10px",
                                                    "letterSpacing": "0.1em",
                                                    "padding": "5px 10px",
                                                    "cursor": "pointer",
                                                    "borderRadius": "3px",
                                                    "flexShrink": "0",
                                                },
                                            ),
                                            dcc.Download(id="csv-download"),
                                        ],
                                        style={
                                            "display": "flex",
                                            "gap": "8px",
                                            "marginBottom": "10px",
                                            "alignItems": "center",
                                            "flexWrap": "wrap",
                                        },
                                    ),
                                    html.Div(id="watchlist-chips", style={"display": "none"}),
                                    html.Div(
                                        id="compare-panel",
                                        style={"display": "none"},
                                        children=[
                                            html.Div(
                                                [
                                                    html.Div(
                                                        [
                                                            html.Div(
                                                                "SYMBOLS",
                                                                style={
                                                                    "fontSize": "9px",
                                                                    "color": TEXT_DIM,
                                                                    "letterSpacing": "0.1em",
                                                                    "marginBottom": "4px",
                                                                },
                                                            ),
                                                            dcc.Checklist(
                                                                id="compare-symbols",
                                                                options=[
                                                                    {"label": f" {s}", "value": s}
                                                                    for s in _wl_compare
                                                                ],
                                                                value=[],
                                                                inline=True,
                                                                style={
                                                                    "fontSize": "11px",
                                                                    "color": TEXT_MAIN,
                                                                    "display": "flex",
                                                                    "flexWrap": "wrap",
                                                                    "gap": "8px",
                                                                },
                                                                labelStyle={
                                                                    "display": "flex",
                                                                    "alignItems": "center",
                                                                    "gap": "3px",
                                                                    "cursor": "pointer",
                                                                },
                                                            ),
                                                        ],
                                                        style={"flex": "1"},
                                                    ),
                                                    html.Div(
                                                        [
                                                            html.Div(
                                                                "PERIOD",
                                                                style={
                                                                    "fontSize": "9px",
                                                                    "color": TEXT_DIM,
                                                                    "letterSpacing": "0.1em",
                                                                    "marginBottom": "4px",
                                                                },
                                                            ),
                                                            dcc.Dropdown(
                                                                id="compare-period",
                                                                options=[
                                                                    {"label": p, "value": p}
                                                                    for p in [
                                                                        "1d",
                                                                        "5d",
                                                                        "1mo",
                                                                        "3mo",
                                                                    ]
                                                                ],
                                                                value="1mo",
                                                                clearable=False,
                                                                style={
                                                                    "width": "80px",
                                                                    "background": BG_CARD,
                                                                    "color": TEXT_MAIN,
                                                                    "fontFamily": FONT,
                                                                    "fontSize": "11px",
                                                                },
                                                            ),
                                                        ]
                                                    ),
                                                ],
                                                style={
                                                    "display": "flex",
                                                    "gap": "16px",
                                                    "alignItems": "flex-start",
                                                    "marginBottom": "8px",
                                                },
                                            ),
                                            dcc.Graph(
                                                id="compare-chart",
                                                config={"displayModeBar": False},
                                                style={"height": "260px"},
                                            ),
                                        ],
                                    ),
                                    html.Div(id="watchlist-table"),
                                ],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "12px 14px",
                                    "marginBottom": "12px",
                                },
                            ),
                            # D) Screener bar
                            html.Div(
                                [
                                    _section_label("SCREENER"),
                                    html.Div(
                                        [
                                            html.Div(
                                                "RSI RANGE",
                                                style={
                                                    "fontSize": "9px",
                                                    "color": TEXT_DIM,
                                                    "letterSpacing": "0.1em",
                                                    "marginBottom": "4px",
                                                },
                                            ),
                                            dcc.RangeSlider(
                                                id="screener-rsi",
                                                min=0,
                                                max=100,
                                                step=1,
                                                value=[30, 70],
                                                marks={
                                                    0: "0",
                                                    30: "30",
                                                    50: "50",
                                                    70: "70",
                                                    100: "100",
                                                },
                                                tooltip={
                                                    "placement": "bottom",
                                                    "always_visible": False,
                                                },
                                            ),
                                        ],
                                        style={"marginBottom": "12px"},
                                    ),
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Div(
                                                        "CHG% MIN",
                                                        style={
                                                            "fontSize": "9px",
                                                            "color": TEXT_DIM,
                                                            "marginBottom": "3px",
                                                        },
                                                    ),
                                                    dcc.Input(
                                                        id="screener-chg-min",
                                                        type="number",
                                                        placeholder="-5",
                                                        style={**_input_style, "width": "80px"},
                                                    ),
                                                ]
                                            ),
                                            html.Div(
                                                [
                                                    html.Div(
                                                        "CHG% MAX",
                                                        style={
                                                            "fontSize": "9px",
                                                            "color": TEXT_DIM,
                                                            "marginBottom": "3px",
                                                        },
                                                    ),
                                                    dcc.Input(
                                                        id="screener-chg-max",
                                                        type="number",
                                                        placeholder="5",
                                                        style={**_input_style, "width": "80px"},
                                                    ),
                                                ]
                                            ),
                                            html.Div(
                                                [
                                                    dcc.Checklist(
                                                        id="screener-flags",
                                                        options=[
                                                            {
                                                                "label": " Above MA20",
                                                                "value": "above_ma20",
                                                            },
                                                            {
                                                                "label": " Vol > 1M",
                                                                "value": "high_volume",
                                                            },
                                                        ],
                                                        value=[],
                                                        style={
                                                            "fontSize": "11px",
                                                            "color": TEXT_MAIN,
                                                            "display": "flex",
                                                            "flexDirection": "column",
                                                            "gap": "4px",
                                                        },
                                                        labelStyle={
                                                            "display": "flex",
                                                            "alignItems": "center",
                                                            "gap": "4px",
                                                            "cursor": "pointer",
                                                        },
                                                    ),
                                                ],
                                                style={"display": "flex", "alignItems": "center"},
                                            ),
                                            html.Button(
                                                "RUN SCREENER",
                                                id="btn-screener-run",
                                                n_clicks=0,
                                                style={
                                                    **_btn_style,
                                                    "border": f"1px solid {PURPLE}",
                                                    "color": PURPLE,
                                                    "letterSpacing": "0.12em",
                                                    "padding": "6px 14px",
                                                },
                                            ),
                                            html.Button(
                                                "CLEAR",
                                                id="btn-screener-clear",
                                                n_clicks=0,
                                                style={
                                                    **_btn_style,
                                                    "border": f"1px solid {BORDER}",
                                                    "color": TEXT_DIM,
                                                    "letterSpacing": "0.12em",
                                                    "padding": "6px 10px",
                                                },
                                            ),
                                        ],
                                        style={
                                            "display": "flex",
                                            "gap": "16px",
                                            "alignItems": "flex-end",
                                            "marginBottom": "12px",
                                        },
                                    ),
                                    html.Div(id="screener-results"),
                                ],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "12px 14px",
                                },
                            ),
                            # E) Price Alerts — compact one-line input row
                            html.Div(
                                [
                                    _section_label("PRICE ALERTS"),
                                    html.Div(id="alert-banner", style={"display": "none"}),
                                    html.Div(
                                        [
                                            dcc.Input(
                                                id="alert-symbol-input",
                                                placeholder="Symbol",
                                                debounce=False,
                                                style=_alert_input_style,
                                            ),
                                            dcc.Dropdown(
                                                id="alert-direction-dropdown",
                                                options=[
                                                    {"label": "ABOVE", "value": "above"},
                                                    {"label": "BELOW", "value": "below"},
                                                ],
                                                value="above",
                                                clearable=False,
                                                style={
                                                    "width": "95px",
                                                    "background": BG_CARD,
                                                    "color": TEXT_MAIN,
                                                    "fontFamily": FONT,
                                                    "fontSize": "11px",
                                                },
                                            ),
                                            dcc.Input(
                                                id="alert-price-input",
                                                type="number",
                                                placeholder="$190.00",
                                                debounce=False,
                                                style=_alert_input_style,
                                            ),
                                            html.Button(
                                                "SET",
                                                id="btn-set-alert",
                                                n_clicks=0,
                                                style={
                                                    "background": "transparent",
                                                    "border": f"1px solid {GREEN}",
                                                    "color": GREEN,
                                                    "fontFamily": FONT,
                                                    "fontSize": "10px",
                                                    "letterSpacing": "0.1em",
                                                    "padding": "5px 10px",
                                                    "cursor": "pointer",
                                                    "borderRadius": "3px",
                                                    "flexShrink": "0",
                                                },
                                            ),
                                        ],
                                        style={
                                            "display": "flex",
                                            "gap": "6px",
                                            "marginBottom": "10px",
                                            "alignItems": "center",
                                            "flexWrap": "nowrap",
                                        },
                                    ),
                                    html.Div(id="alerts-list"),
                                ],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "12px 14px",
                                    "marginTop": "12px",
                                },
                            ),
                        ],
                        style={
                            "width": "65%",
                            "paddingRight": "10px",
                            "display": "flex",
                            "flexDirection": "column",
                        },
                    ),
                    # Right column (35%)
                    html.Div(
                        [
                            html.Div(
                                [
                                    _section_label("📅 ECONOMIC CALENDAR"),
                                    html.Div(
                                        id="economic-calendar-content",
                                        style={
                                            "maxHeight": "240px",
                                            "overflowY": "auto",
                                            "overflowX": "hidden",
                                            "paddingRight": "4px",
                                        },
                                    ),
                                ],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "12px 14px",
                                    "marginBottom": "12px",
                                },
                            ),
                            # News feed
                            html.Div(
                                [
                                    html.Div(
                                        id="news-header",
                                        style={
                                            "fontSize": "9px",
                                            "fontWeight": "700",
                                            "letterSpacing": "0.18em",
                                            "color": TEXT_DIM,
                                            "textTransform": "uppercase",
                                            "borderBottom": f"1px solid {BORDER}",
                                            "paddingBottom": "6px",
                                            "marginBottom": "10px",
                                        },
                                    ),
                                    html.Div(
                                        id="news-feed-content",
                                        style={"maxHeight": "340px", "overflowY": "auto"},
                                    ),
                                    html.Div(id="news-feed", style={"display": "none"}),
                                ],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "12px 14px",
                                    "marginBottom": "12px",
                                },
                            ),
                            # Chart overlay (1mo OHLCV)
                            html.Div(
                                [html.Div(id="chart-overlay-content")],
                                style={
                                    "background": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "padding": "0",
                                    "overflow": "hidden",
                                },
                            ),
                        ],
                        style={
                            "width": "35%",
                            "paddingLeft": "10px",
                            "display": "flex",
                            "flexDirection": "column",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "flex": "1",
                    "padding": "14px 16px",
                    "overflowY": "auto",
                    "minHeight": "0",
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
