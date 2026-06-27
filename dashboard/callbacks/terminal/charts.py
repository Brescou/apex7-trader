"""APEX-7 — Terminal tab — symbol chart, news, and comparison callbacks."""

import logging

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from agents.shared.watchlist import get_watchlist
from market_data import (
    fetch_comparison,
    fetch_earnings_calendar,
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

logger = logging.getLogger("apex7.terminal.charts")

_CHART_PERIODS = ["1d", "5d", "1mo", "3mo", "6mo", "1y"]


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
    except Exception as exc:
        logger.debug("fundamentals strip: fetch failed for %s: %s", symbol, exc)
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


def _period_selector(current_period: str) -> html.Div:
    """Row of period toggle buttons."""
    btns = []
    for p in _CHART_PERIODS:
        active = p == current_period
        btns.append(
            html.Button(
                p.upper(),
                id={"type": "chart-period-btn", "index": p},
                n_clicks=0,
                style={
                    "background": f"{BLUE}33" if active else "transparent",
                    "border": f"1px solid {BLUE if active else BORDER}",
                    "color": BLUE if active else TEXT_DIM,
                    "fontFamily": FONT,
                    "fontSize": "8px",
                    "padding": "2px 7px",
                    "cursor": "pointer",
                    "borderRadius": "2px",
                    "letterSpacing": "0.08em",
                    "transition": "all 0.1s",
                },
            )
        )
    return html.Div(
        btns,
        style={
            "display": "flex",
            "gap": "4px",
            "padding": "4px 8px 2px",
            "justifyContent": "flex-end",
        },
    )


def _ma_series(closes: list, n: int) -> list | None:
    """Simple moving average; returns None when insufficient data."""
    if len(closes) < n:
        return None
    result = [None] * (n - 1)
    for i in range(n - 1, len(closes)):
        result.append(sum(closes[i - n + 1 : i + 1]) / n)
    return result


@app.callback(
    Output("chart-period-store", "data"),
    Input({"type": "chart-period-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _update_chart_period(n_clicks_list):
    if not any(n for n in n_clicks_list if n):
        return no_update
    return ctx.triggered_id["index"]


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
    except Exception as exc:
        logger.warning("news panel: fetch_news failed for %s: %s", sym, exc)
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
    except Exception as exc:
        logger.warning("news content: fetch_news failed for %s: %s", sym, exc)
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
    Input("chart-period-store", "data"),
    State("main-tabs", "value"),
)
def _update_chart_overlay(symbol, period, active_tab):
    if active_tab != "terminal" or not symbol:
        return no_update

    period = period or "1mo"
    data = fetch_ohlcv(symbol, period=period)
    if not data:
        return html.Div(
            f"No data for {symbol}",
            style={"color": TEXT_DIM, "fontSize": "11px", "padding": "12px"},
        )

    dates = [d["date"] for d in data]
    opens = [d["open"] for d in data]
    highs = [d["high"] for d in data]
    lows = [d["low"] for d in data]
    closes = [d["close"] for d in data]
    volumes = [d["volume"] for d in data]

    ma20 = _ma_series(closes, 20)
    ma50 = _ma_series(closes, 50)
    ma200 = _ma_series(closes, 200)

    # Earnings annotations on the price chart
    earnings_dates: set[str] = set()
    try:
        cal = fetch_earnings_calendar([symbol])
        entry = cal.get(symbol)
        if entry and entry.get("earnings_date"):
            earnings_dates.add(str(entry["earnings_date"])[:10])
    except Exception:
        pass

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.73, 0.27],
        vertical_spacing=0.02,
    )

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=dates,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name=symbol,
            increasing_line_color="#22c55e",
            decreasing_line_color="#ef4444",
            increasing_fillcolor="#22c55e",
            decreasing_fillcolor="#ef4444",
            showlegend=False,
            line=dict(width=1),
        ),
        row=1,
        col=1,
    )

    if ma20:
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=ma20,
                mode="lines",
                name="MA20",
                line=dict(color=YELLOW, width=1),
            ),
            row=1,
            col=1,
        )
    if ma50:
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=ma50,
                mode="lines",
                name="MA50",
                line=dict(color=BLUE, width=1),
            ),
            row=1,
            col=1,
        )
    if ma200:
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=ma200,
                mode="lines",
                name="MA200",
                line=dict(color=PURPLE, width=1, dash="dot"),
            ),
            row=1,
            col=1,
        )

    # Volume bars (green if close >= open, red otherwise)
    vol_colors = ["#22c55e" if c >= o else "#ef4444" for c, o in zip(closes, opens)]
    fig.add_trace(
        go.Bar(
            x=dates,
            y=volumes,
            name="Volume",
            marker_color=vol_colors,
            marker_opacity=0.55,
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Earnings marker (vertical dashed line annotation)
    annotations = []
    for ed in earnings_dates:
        if ed in dates:
            annotations.append(
                dict(
                    x=ed,
                    yref="paper",
                    y=0,
                    y1=1,
                    xref="x",
                    type="line",
                    line=dict(color=ORANGE, width=1, dash="dot"),
                )
            )
            annotations.append(
                dict(
                    x=ed,
                    y=1.0,
                    xref="x",
                    yref="paper",
                    text="E",
                    showarrow=False,
                    font=dict(size=9, color=ORANGE),
                    bgcolor=f"{ORANGE}22",
                    bordercolor=ORANGE,
                    borderwidth=1,
                    xanchor="center",
                )
            )

    common_axis = dict(
        showgrid=True,
        gridcolor=BORDER,
        gridwidth=1,
        tickfont=dict(size=9, color=TEXT_DIM, family=FONT),
        showline=False,
        zeroline=False,
    )

    fig.update_layout(
        title=dict(
            text=f"{symbol} — {period.upper()}",
            font=dict(size=11, color=TEXT_DIM, family=FONT),
            x=0,
        ),
        paper_bgcolor=BG_CARD,
        plot_bgcolor=BG_CARD,
        margin=dict(l=8, r=8, t=28, b=4),
        height=300,
        showlegend=True,
        legend=dict(
            orientation="h",
            x=0,
            y=1.06,
            font=dict(size=8, color=TEXT_DIM, family=FONT),
            bgcolor="rgba(0,0,0,0)",
            traceorder="normal",
        ),
        xaxis_rangeslider_visible=False,
        xaxis=dict(**common_axis),
        xaxis2=dict(**common_axis),
        yaxis=dict(**common_axis, tickprefix="$"),
        yaxis2=dict(**{**common_axis, "tickformat": "~s"}),
        annotations=annotations,
        font=dict(family=FONT, color=TEXT_MAIN, size=9),
    )

    return html.Div(
        [
            _period_selector(period),
            dcc.Graph(
                figure=fig,
                config={"displayModeBar": False},
                style={"height": "300px"},
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
    except Exception as exc:
        logger.warning("comparison chart: fetch failed for %s: %s", symbols, exc)
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
