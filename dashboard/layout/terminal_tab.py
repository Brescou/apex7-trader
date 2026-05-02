"""APEX-7 — Terminal tab: CLI interface + hidden market data DOM."""

import dash_mantine_components as dmc
from dash import dcc, html

from agents.shared.watchlist import get_watchlist
from dashboard.server import (
    BG_DEEP,
    BORDER_INNER,
    FONT,
    GREEN,
    TEXT_FAINT,
    TEXT_GHOST,
)


def _cli_line(src: str, src_class: str, body: str) -> html.Div:
    return html.Div(
        className="cli-line",
        children=[
            html.Span("—", className="cli-ts", style={"color": "#122535"}),
            html.Span(f"[{src}]", className=f"cli-src {src_class}"),
            html.Span(body, className="cli-body"),
        ],
    )


def _tab_terminal() -> html.Div:
    _wl = get_watchlist()
    _hints = [
        "help",
        "status",
        "positions",
        "portfolio",
        "agents",
        "buy AAPL 5",
        "sell TSLA 1",
        "clear",
    ]

    cli_section = html.Div(
        style={
            "display": "flex",
            "flexDirection": "column",
            "height": "calc(100vh - 30px)",
            "background": BG_DEEP,
            "overflow": "hidden",
        },
        children=[
            # Header row
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "6px",
                    "padding": "4px 10px",
                    "borderBottom": f"1px solid {BORDER_INNER}",
                    "flexShrink": "0",
                },
                children=[
                    html.Div(
                        className="term-led",
                        style={
                            "width": "6px",
                            "height": "6px",
                            "borderRadius": "50%",
                            "background": GREEN,
                        },
                    ),
                    html.Span(
                        "APEX-7 SYSTEM TERMINAL",
                        style={
                            "fontSize": "8px",
                            "color": TEXT_FAINT,
                            "letterSpacing": "0.12em",
                            "fontWeight": "700",
                        },
                    ),
                    html.Span(
                        id="cli-clock",
                        style={
                            "fontSize": "7px",
                            "color": TEXT_GHOST,
                            "marginLeft": "auto",
                        },
                    ),
                ],
            ),
            # Scrollable output
            dmc.ScrollArea(
                id="cli-output",
                style={
                    "flex": "1",
                    "padding": "2px 0",
                    "fontSize": "9px",
                    "lineHeight": "1.75",
                },
                children=[
                    _cli_line("SYS", "tc-c", "Apex-7 Trading System v2.4.1 — agent initialized"),
                    _cli_line("SYS", "tc-c", "Type 'help' for available commands."),
                    _cli_line("---", "tc-d", "─" * 58),
                ],
            ),
            # Prompt + hint buttons footer
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "6px",
                    "padding": "5px 10px",
                    "borderTop": f"1px solid {BORDER_INNER}",
                    "flexShrink": "0",
                    "flexWrap": "wrap",
                },
                children=[
                    html.Span(
                        "apex7>",
                        style={
                            "fontSize": "9px",
                            "color": GREEN,
                            "fontWeight": "700",
                            "flexShrink": "0",
                        },
                    ),
                    dcc.Input(
                        id="cli-input",
                        type="text",
                        placeholder="type command…",
                        debounce=False,
                        n_submit=0,
                        autoComplete="off",
                        style={
                            "flex": "1",
                            "background": "transparent",
                            "border": "none",
                            "outline": "none",
                            "color": "#b0ccd4",
                            "fontFamily": FONT,
                            "fontSize": "9px",
                            "minWidth": "80px",
                        },
                    ),
                    html.Div(
                        style={"display": "flex", "gap": "4px", "flexWrap": "wrap"},
                        children=[
                            html.Button(
                                h,
                                id=f"cli-hint-{i}",
                                n_clicks=0,
                                style={
                                    "background": "none",
                                    "border": f"1px solid {BORDER_INNER}",
                                    "color": TEXT_GHOST,
                                    "fontFamily": FONT,
                                    "fontSize": "7px",
                                    "padding": "1px 5px",
                                    "cursor": "pointer",
                                    "letterSpacing": "0.1em",
                                    "borderRadius": "0",
                                    "transition": "all 0.1s",
                                },
                            )
                            for i, h in enumerate(_hints)
                        ],
                    ),
                ],
            ),
        ],
    )

    # ── Hidden market-data DOM (keeps existing terminal callbacks alive) ─────
    hidden_market_data = html.Div(
        style={"display": "none"},
        children=[
            html.Div(id="macro-bar-content"),
            dcc.Input(id="watchlist-add-input"),
            html.Button("ADD", id="btn-watchlist-add", n_clicks=0),
            html.Button("COMPARE", id="btn-compare", n_clicks=0),
            html.Button("CSV", id="btn-export-csv", n_clicks=0),
            dcc.Download(id="csv-download"),
            html.Div(id="watchlist-chips"),
            html.Div(
                id="compare-panel",
                children=[
                    dcc.Checklist(
                        id="compare-symbols",
                        options=[{"label": s, "value": s} for s in _wl],
                        value=[],
                    ),
                    dcc.Dropdown(
                        id="compare-period",
                        options=[{"label": p, "value": p} for p in ["1d", "5d", "1mo", "3mo"]],
                        value="1mo",
                        clearable=False,
                    ),
                    dcc.Graph(id="compare-chart", config={"displayModeBar": False}),
                ],
            ),
            html.Div(id="watchlist-table"),
            dcc.RangeSlider(id="screener-rsi", min=0, max=100, step=1, value=[30, 70]),
            dcc.Input(id="screener-chg-min", type="number"),
            dcc.Input(id="screener-chg-max", type="number"),
            dcc.Checklist(
                id="screener-flags",
                options=[
                    {"label": "Above MA20", "value": "above_ma20"},
                    {"label": "Vol > 1M", "value": "high_volume"},
                ],
                value=[],
            ),
            html.Button("RUN SCREENER", id="btn-screener-run", n_clicks=0),
            html.Button("CLEAR", id="btn-screener-clear", n_clicks=0),
            html.Div(id="screener-results"),
            dcc.Input(id="alert-symbol-input"),
            dcc.Dropdown(
                id="alert-direction-dropdown",
                options=[
                    {"label": "ABOVE", "value": "above"},
                    {"label": "BELOW", "value": "below"},
                ],
                value="above",
                clearable=False,
            ),
            dcc.Input(id="alert-price-input", type="number"),
            html.Button("SET", id="btn-set-alert", n_clicks=0),
            html.Div(id="alert-banner"),
            html.Div(id="alerts-list"),
            html.Div(id="economic-calendar-content"),
            html.Div(id="sector-rotation-content"),
            html.Div(id="correlation-matrix-warning"),
            html.Div(id="correlation-matrix-content"),
            dcc.Dropdown(
                id="correlation-period-dropdown",
                options=[
                    {"label": "1M", "value": "1mo"},
                    {"label": "3M", "value": "3mo"},
                    {"label": "6M", "value": "6mo"},
                ],
                value="3mo",
                clearable=False,
            ),
            html.Div(id="news-header"),
            html.Div(id="news-feed"),
            html.Div(id="news-feed-content"),
            html.Div(id="chart-overlay-content"),
        ],
    )

    return html.Div(
        style={"height": "100%", "overflow": "hidden"},
        children=[cli_section, hidden_market_data],
    )
