"""APEX-7 — Terminal tab — symbol chart, news, and comparison callbacks."""

import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, no_update

from agents.shared.watchlist import get_watchlist
from market_data import (
    fetch_comparison,
    fetch_fundamentals,
    fetch_news,
    fetch_ohlcv,
    format_market_cap,
)
from dashboard.server import (
    BG_CARD,
    BG_DEEP,
    BLUE,
    BORDER,
    FONT,
    GRAY,
    GREEN,
    ORANGE,
    PURPLE,
    RED,
    TEXT_DIM,
    TEXT_MAIN,
    YELLOW,
    app,
)


def _fallback_active_symbol(symbol) -> str:
    if symbol:
        return symbol
    wl = get_watchlist()
    return wl[0] if wl else "AAPL"


def _fmt_num(value, suffix: str = "", pct: bool = False) -> str:
    """Format a fundamental number, ``—`` when missing."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if pct:
        return f"{v * 100:.2f}%"
    return f"{v:.2f}{suffix}"


def _fundamentals_strip(symbol: str) -> html.Div:
    """Compact fundamentals row (market cap, P/E, fwd P/E, EPS, div, beta).

    Fail-silent: yfinance errors yield an empty payload and a row of ``—``.
    """
    try:
        f = fetch_fundamentals(symbol)
    except Exception:
        f = {}

    cells = [
        ("MKT CAP", format_market_cap(f.get("market_cap"))),
        ("P/E", _fmt_num(f.get("pe_ratio"))),
        ("FWD P/E", _fmt_num(f.get("forward_pe"))),
        ("EPS", _fmt_num(f.get("eps"))),
        ("DIV", _fmt_num(f.get("dividend_yield"), pct=True)),
        ("BETA", _fmt_num(f.get("beta"))),
    ]
    sector = f.get("sector")
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        lbl,
                        style={
                            "fontSize": "8px",
                            "color": TEXT_DIM,
                            "letterSpacing": "0.1em",
                            "display": "block",
                        },
                    ),
                    html.Span(
                        val,
                        style={"fontSize": "11px", "fontWeight": "700", "color": TEXT_MAIN},
                    ),
                ],
                style={"flex": "1", "minWidth": "0", "textAlign": "center"},
            )
            for lbl, val in cells
        ]
        + (
            [
                html.Span(
                    sector,
                    style={
                        "fontSize": "9px",
                        "color": BLUE,
                        "alignSelf": "center",
                        "paddingLeft": "8px",
                        "borderLeft": f"1px solid {BORDER}",
                        "flexShrink": "0",
                    },
                )
            ]
            if sector
            else []
        ),
        style={
            "display": "flex",
            "alignItems": "stretch",
            "gap": "6px",
            "padding": "8px 10px",
            "marginTop": "8px",
            "background": BG_DEEP,
            "border": f"1px solid {BORDER}",
            "borderRadius": "3px",
        },
    )


@app.callback(
    Output("news-feed", "children"),
    Output("news-header", "children"),
    Input("terminal-active-symbol", "data"),
    Input("news-interval", "n_intervals"),
)
def _update_news(symbol, _):
    sym = _fallback_active_symbol(symbol)
    header = f"NEWS — {sym}"

    try:
        items = fetch_news(sym)
    except Exception:
        items = []

    if not items:
        return (
            html.Div(
                "No news available.",
                style={
                    "color": TEXT_DIM,
                    "fontSize": "12px",
                    "fontStyle": "italic",
                    "textAlign": "center",
                    "padding": "20px",
                },
            ),
            header,
        )

    cards = []
    for item in items:
        sentiment = item.get("sentiment", "neutral")
        if sentiment == "positive":
            sent_col = GREEN
            sent_dot = "🟢"
        elif sentiment == "negative":
            sent_col = RED
            sent_dot = "🔴"
        else:
            sent_col = GRAY
            sent_dot = "⚪"

        title = item.get("title", "")
        source = item.get("source", "")
        age = item.get("age", "")
        url = item.get("url", "#")

        cards.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(sent_dot, style={"marginRight": "6px", "fontSize": "10px"}),
                            html.A(
                                title,
                                href=url,
                                target="_blank",
                                style={
                                    "color": TEXT_MAIN,
                                    "fontSize": "12px",
                                    "fontWeight": "600",
                                    "textDecoration": "none",
                                    "lineHeight": "1.4",
                                    "fontFamily": FONT,
                                    "display": "-webkit-box",
                                    "WebkitLineClamp": "2",
                                    "WebkitBoxOrient": "vertical",
                                    "overflow": "hidden",
                                },
                            ),
                        ],
                        style={
                            "display": "flex",
                            "alignItems": "flex-start",
                            "marginBottom": "4px",
                        },
                    ),
                    html.Div(
                        f"{source}  ·  {age}",
                        style={"fontSize": "10px", "color": TEXT_DIM, "marginTop": "2px"},
                    ),
                ],
                style={
                    "borderLeft": f"3px solid {sent_col}",
                    "background": BG_CARD,
                    "padding": "8px 10px",
                    "marginBottom": "3px",
                    "borderRadius": "0 4px 4px 0",
                    "display": "flex",
                    "flexDirection": "column",
                    "gap": "3px",
                },
            )
        )

    return html.Div(cards), header


@app.callback(
    Output("news-feed-content", "children"),
    Input("terminal-active-symbol", "data"),
    Input("news-interval", "n_intervals"),
    State("main-tabs", "value"),
)
def _update_news_content(symbol, _, active_tab):
    if active_tab != "terminal":
        return no_update
    sym = _fallback_active_symbol(symbol)

    try:
        items = fetch_news(sym)
    except Exception:
        items = []

    if not items:
        return html.Div(
            "No news available.",
            style={
                "color": TEXT_DIM,
                "fontSize": "12px",
                "fontStyle": "italic",
                "textAlign": "center",
                "padding": "20px",
            },
        )

    cards = []
    for item in items:
        sentiment = item.get("sentiment", "neutral")
        if sentiment == "positive":
            sent_dot = "🟢"
            border_col = GREEN
        elif sentiment == "negative":
            sent_dot = "🔴"
            border_col = RED
        else:
            sent_dot = "⚪"
            border_col = "#334155"

        title = item.get("title", "")
        source = item.get("source", "")
        age = item.get("age", "")
        url = item.get("url", "#")

        cards.append(
            html.Div(
                [
                    html.Div(
                        style={"display": "flex", "gap": "8px", "alignItems": "flex-start"},
                        children=[
                            html.Span(
                                sent_dot,
                                style={
                                    "fontSize": "10px",
                                    "marginTop": "2px",
                                    "flexShrink": "0",
                                },
                            ),
                            html.Div(
                                [
                                    html.A(
                                        title,
                                        href=url,
                                        target="_blank",
                                        style={
                                            "color": TEXT_MAIN,
                                            "textDecoration": "none",
                                            "fontSize": "12px",
                                            "lineHeight": "1.4",
                                            "display": "-webkit-box",
                                            "WebkitLineClamp": "2",
                                            "WebkitBoxOrient": "vertical",
                                            "overflow": "hidden",
                                        },
                                    ),
                                    html.Div(
                                        f"{source} · {age}",
                                        style={
                                            "color": TEXT_DIM,
                                            "fontSize": "10px",
                                            "marginTop": "2px",
                                        },
                                    ),
                                ]
                            ),
                        ],
                    )
                ],
                style={
                    "padding": "8px 10px",
                    "borderLeft": f"3px solid {border_col}",
                    "marginBottom": "3px",
                    "background": BG_CARD,
                    "borderRadius": "0 4px 4px 0",
                    "display": "flex",
                    "flexDirection": "column",
                    "gap": "3px",
                },
            )
        )

    return html.Div(cards)


@app.callback(
    Output("chart-overlay-content", "children"),
    Input("terminal-active-symbol", "data"),
    State("main-tabs", "value"),
)
def _update_chart_overlay(symbol, active_tab):
    if active_tab != "terminal" or not symbol:
        return no_update

    data = fetch_ohlcv(symbol, period="1mo")
    if not data:
        return html.Div(
            f"No data for {symbol}",
            style={
                "color": TEXT_DIM,
                "fontSize": "11px",
                "padding": "12px",
            },
        )

    closes = [d["close"] for d in data]
    dates = [d["date"] for d in data]
    color = GREEN if closes[-1] >= closes[0] else RED
    max_idx = closes.index(max(closes))
    min_idx = closes.index(min(closes))

    h = color.lstrip("#")
    r_c, g_c, b_c = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=closes,
            mode="lines",
            line=dict(color=color, width=1.5),
            fill="tozeroy",
            fillcolor=f"rgba({r_c},{g_c},{b_c},0.06)",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[dates[max_idx]],
            y=[closes[max_idx]],
            mode="markers+text",
            marker=dict(color=YELLOW, size=5),
            text=[f"${closes[max_idx]:.2f}"],
            textposition="top center",
            textfont=dict(size=9, color=YELLOW),
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[dates[min_idx]],
            y=[closes[min_idx]],
            mode="markers+text",
            marker=dict(color=RED, size=5),
            text=[f"${closes[min_idx]:.2f}"],
            textposition="bottom center",
            textfont=dict(size=9, color=RED),
            showlegend=False,
        )
    )
    fig.update_layout(
        title=dict(
            text=f"{symbol} — 1mo",
            font=dict(size=11, color=TEXT_DIM),
            x=0,
        ),
        paper_bgcolor=BG_CARD,
        plot_bgcolor=BG_CARD,
        margin=dict(l=8, r=8, t=32, b=24),
        height=200,
        showlegend=False,
        xaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            tickfont=dict(size=9, color=TEXT_DIM),
            showline=False,
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            tickfont=dict(size=9, color=TEXT_DIM),
            tickprefix="$",
            showline=False,
            zeroline=False,
        ),
    )
    return html.Div(
        [
            dcc.Graph(
                figure=fig,
                config={"displayModeBar": False},
                style={"height": "200px"},
            ),
            _fundamentals_strip(symbol),
        ]
    )


@app.callback(
    Output("compare-chart", "figure"),
    Input("compare-period", "value"),
    Input("compare-symbols", "value"),
    prevent_initial_call=False,
)
def _update_comparison(period, symbols):
    if not symbols:
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor=BG_DEEP,
            plot_bgcolor=BG_CARD,
            font=dict(family=FONT, color=TEXT_MAIN, size=10),
            margin=dict(l=40, r=20, t=30, b=40),
            height=260,
            xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=8, color=TEXT_DIM)),
            yaxis=dict(
                showgrid=True,
                gridcolor=BORDER,
                zeroline=False,
                tickfont=dict(size=8, color=TEXT_DIM),
            ),
            annotations=[
                dict(
                    text="Select symbols above to compare",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(family=FONT, size=11, color=TEXT_DIM),
                )
            ],
        )
        return fig

    try:
        data = fetch_comparison(symbols, period or "1mo")
    except Exception:
        data = {}

    palette = [BLUE, PURPLE, GREEN, RED, ORANGE]
    fig = go.Figure()
    for i, sym in enumerate(symbols):
        series = data.get(sym, [])
        if not series:
            continue
        col = palette[i % len(palette)]
        fig.add_trace(
            go.Scatter(
                x=[p["date"] for p in series],
                y=[p["value"] for p in series],
                mode="lines",
                name=sym,
                line=dict(color=col, width=1.5),
            )
        )
    fig.update_layout(
        paper_bgcolor=BG_DEEP,
        plot_bgcolor=BG_CARD,
        font=dict(family=FONT, color=TEXT_MAIN, size=10),
        margin=dict(l=40, r=20, t=30, b=40),
        height=260,
        showlegend=True,
        legend=dict(
            x=0, y=1, bgcolor="rgba(0,0,0,0)", font=dict(family=FONT, size=9, color=TEXT_DIM)
        ),
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=8, color=TEXT_DIM)),
        yaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            zeroline=False,
            tickfont=dict(size=8, color=TEXT_DIM),
            title=dict(text="Normalized (base=100)", font=dict(size=8, color=TEXT_DIM)),
        ),
    )
    return fig
