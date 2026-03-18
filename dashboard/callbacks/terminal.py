"""APEX-7 — Terminal tab callbacks (16 callbacks)."""

import time

import dash
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from config import WATCHLIST
from market_data import (
    fetch_comparison,
    fetch_macro,
    fetch_news,
    fetch_ohlcv,
    fetch_sparkline,
    fetch_watchlist_prices,
    run_screener,
)
from dashboard.layout import _fmt_volume, _make_sparkline_fig, _watchlist_row
from dashboard.server import (
    BG_CARD,
    BG_DEEP,
    BG_HOVER,
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

_MACRO_KEYS = {"VIX": "^VIX", "SPY": "SPY", "DXY": "DX-Y.NYB"}


def _mini_macro_chart(spark_data, chg):
    """80x30px sparkline for macro bar blocs."""
    if not spark_data:
        return html.Div(style={"height": "30px", "width": "80px"})
    prices = [d["price"] for d in spark_data[-5:]]
    color = GREEN if (chg is not None and chg > 0) else RED
    fig = go.Figure(go.Scatter(y=prices, mode="lines", line=dict(color=color, width=1.5)))
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        height=30,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return dcc.Graph(
        figure=fig,
        config={"displayModeBar": False},
        style={"height": "30px", "width": "80px"},
    )


@app.callback(
    Output("macro-bar-content", "children"),
    Input("macro-interval", "n_intervals"),
    prevent_initial_call=False,
)
def _update_macro_bar(_):
    try:
        data = fetch_macro()
    except Exception:
        data = {}

    blocs = []
    for key in ("VIX", "SPY", "DXY"):
        yf_sym = _MACRO_KEYS[key]
        d = data.get(key, {})
        price = d.get("price")
        chg = d.get("change_pct")
        dirn = d.get("direction", "flat")

        price_str = f"{float(price):.2f}" if price is not None else "—"

        if chg is None:
            chg_str = "—"
            chg_col = TEXT_DIM
        else:
            chg_f = float(chg)
            chg_col = GREEN if dirn == "up" else (RED if dirn == "down" else TEXT_DIM)
            arrow = "▲ " if dirn == "up" else ("▼ " if dirn == "down" else "")
            chg_str = f"{arrow}{chg_f:+.2f}%"

        try:
            spark = fetch_sparkline(yf_sym)
        except Exception:
            spark = []

        mini = _mini_macro_chart(spark, float(chg) if chg is not None else None)

        is_last = key == "DXY"
        blocs.append(
            html.Div(
                [
                    html.Span(
                        key,
                        style={
                            "fontSize": "11px",
                            "color": TEXT_DIM,
                            "letterSpacing": "2px",
                            "fontWeight": "700",
                            "textTransform": "uppercase",
                        },
                    ),
                    html.Div(
                        [
                            html.Span(
                                price_str,
                                style={
                                    "fontSize": "20px",
                                    "fontWeight": "700",
                                    "color": TEXT_MAIN,
                                },
                            ),
                            html.Span(
                                chg_str,
                                style={
                                    "fontSize": "13px",
                                    "color": chg_col,
                                    "marginLeft": "8px",
                                },
                            ),
                        ],
                        style={"display": "flex", "alignItems": "baseline"},
                    ),
                    mini,
                ],
                style={
                    "flex": "1",
                    "display": "flex",
                    "flexDirection": "column",
                    "gap": "2px",
                    "padding": "8px 16px",
                    "borderRight": "none" if is_last else f"1px solid {BORDER}",
                },
            )
        )

    ts = data.get("updated_at", "")
    ts_el = html.Span(
        f"⏱ {ts}" if ts else "",
        style={
            "fontSize": "9px",
            "color": TEXT_DIM,
            "marginLeft": "auto",
            "letterSpacing": "0.08em",
            "alignSelf": "flex-end",
            "paddingBottom": "8px",
        },
    )

    return blocs + [ts_el]


@app.callback(
    Output("terminal-watchlist", "data"),
    Input("btn-watchlist-add", "n_clicks"),
    State("watchlist-add-input", "value"),
    State("terminal-watchlist", "data"),
    prevent_initial_call=True,
)
def _add_symbol(_, symbol, watchlist):
    if not symbol:
        return watchlist or []
    sym = symbol.strip().upper()
    wl = list(watchlist or [])
    if sym and sym not in wl:
        wl.append(sym)
    return wl


@app.callback(
    Output("terminal-watchlist", "data", allow_duplicate=True),
    Input({"type": "watchlist-remove", "index": ALL}, "n_clicks"),
    State("terminal-watchlist", "data"),
    prevent_initial_call=True,
)
def _remove_symbol(n_clicks_list, watchlist):
    if not any(n_clicks_list):
        return watchlist or []
    sym = ctx.triggered_id["index"]
    wl = [s for s in (watchlist or []) if s != sym]
    return wl


@app.callback(
    Output("watchlist-chips", "children"),
    Output("watchlist-table", "children"),
    Input("terminal-watchlist", "data"),
    Input("watchlist-interval", "n_intervals"),
    Input("terminal-active-symbol", "data"),
    Input("screener-active-store", "data"),
    Input("screener-results-store", "data"),
)
def _update_watchlist(watchlist, _, active_sym, screener_active, screener_results):
    wl = watchlist or []
    screener_matched = set(screener_results or [])
    is_screener_active = bool(screener_active)

    if not wl:
        empty_card = html.Div(
            "No symbols. Add one above.",
            style={
                "color": TEXT_DIM,
                "fontSize": "11px",
                "fontStyle": "italic",
                "padding": "10px",
            },
        )
        return [], empty_card

    try:
        prices = fetch_watchlist_prices(wl)
    except Exception:
        prices = {}

    # Build 2-column symbol card grid
    cards = []
    for sym in wl:
        d = prices.get(sym, {})
        chg_pct = d.get("change_pct", 0.0) or 0.0
        chg_abs = d.get("change_abs", 0.0) or 0.0
        price = d.get("price", 0.0) or 0.0
        rsi = d.get("rsi_14")
        above = d.get("above_ma20", None)
        volume = d.get("volume", 0)
        chg_col = GREEN if chg_pct >= 0 else RED
        dot_col = GREEN if chg_pct >= 0 else RED
        active = sym == active_sym

        try:
            spark = fetch_sparkline(sym)
        except Exception:
            spark = []

        # RSI badge
        if rsi is not None:
            try:
                rsi_f = float(rsi)
                if rsi_f < 30:
                    rsi_badge = html.Span(
                        f"RSI {rsi_f:.0f} oversold",
                        style={
                            "fontSize": "10px",
                            "color": GREEN,
                            "background": "rgba(16,185,129,0.15)",
                            "padding": "1px 5px",
                            "borderRadius": "2px",
                        },
                    )
                elif rsi_f > 70:
                    rsi_badge = html.Span(
                        f"RSI {rsi_f:.0f} overbought",
                        style={
                            "fontSize": "10px",
                            "color": RED,
                            "background": "rgba(239,68,68,0.15)",
                            "padding": "1px 5px",
                            "borderRadius": "2px",
                        },
                    )
                else:
                    rsi_badge = html.Span(
                        f"RSI {rsi_f:.0f}",
                        style={"fontSize": "10px", "color": TEXT_DIM},
                    )
            except (TypeError, ValueError):
                rsi_badge = html.Span("RSI —", style={"fontSize": "10px", "color": TEXT_DIM})
        else:
            rsi_badge = html.Span("RSI —", style={"fontSize": "10px", "color": TEXT_DIM})

        # MA20 indicator
        if above is True:
            ma20_label = "▲"
            ma20_col = GREEN
        elif above is False:
            ma20_label = "▼"
            ma20_col = RED
        else:
            ma20_label = "—"
            ma20_col = TEXT_DIM

        # Card border: white if active, YELLOW if screener match, else BORDER
        if active:
            border_color = "#ffffff"
        elif is_screener_active and sym in screener_matched:
            border_color = YELLOW
        else:
            border_color = BORDER

        card = html.Div(
            [
                # Header row: dot + symbol + remove button
                html.Div(
                    [
                        html.Span(
                            "●",
                            style={
                                "color": dot_col,
                                "marginRight": "6px",
                                "fontSize": "10px",
                            },
                        ),
                        html.Span(
                            sym,
                            style={
                                "fontSize": "12px",
                                "fontWeight": "700",
                                "color": TEXT_MAIN,
                                "flex": "1",
                            },
                        ),
                        html.Button(
                            "×",
                            id={"type": "watchlist-remove", "index": sym},
                            n_clicks=0,
                            style={
                                "background": "transparent",
                                "border": "none",
                                "color": TEXT_DIM,
                                "cursor": "pointer",
                                "fontSize": "14px",
                                "padding": "0",
                                "fontFamily": FONT,
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "marginBottom": "6px",
                    },
                ),
                # Price + change row
                html.Div(
                    [
                        html.Span(
                            f"${price:.2f}",
                            style={
                                "fontSize": "20px",
                                "fontWeight": "700",
                                "color": TEXT_MAIN,
                                "marginRight": "8px",
                            },
                        ),
                        html.Span(
                            f"{'▲' if chg_pct >= 0 else '▼'} {chg_pct:+.2f}%",
                            style={
                                "fontSize": "12px",
                                "fontWeight": "700",
                                "color": chg_col,
                            },
                        ),
                        html.Span(
                            f" {chg_abs:+.2f}",
                            style={"fontSize": "11px", "color": chg_col},
                        ),
                    ],
                    style={"marginBottom": "6px"},
                ),
                # RSI + MA20 + VOL row
                html.Div(
                    [
                        rsi_badge,
                        html.Span(
                            f"MA20 {ma20_label}",
                            style={
                                "fontSize": "10px",
                                "color": ma20_col,
                                "marginLeft": "8px",
                            },
                        ),
                        html.Span(
                            f"VOL {_fmt_volume(volume)}",
                            style={
                                "fontSize": "10px",
                                "color": TEXT_DIM,
                                "marginLeft": "8px",
                            },
                        ),
                    ],
                    style={"marginBottom": "6px"},
                ),
                # Sparkline
                dcc.Graph(
                    figure=_make_sparkline_fig(spark or []),
                    config={"displayModeBar": False},
                    style={"height": "35px", "margin": "0"},
                ),
                # Invisible click overlay button
                html.Button(
                    "",
                    id={"type": "watchlist-row-btn", "index": sym},
                    n_clicks=0,
                    style={
                        "position": "absolute",
                        "inset": "0",
                        "background": "transparent",
                        "border": "none",
                        "cursor": "pointer",
                        "width": "100%",
                        "height": "100%",
                    },
                ),
            ],
            style={
                "position": "relative",
                "background": BG_CARD,
                "border": f"1px solid {border_color}",
                "borderRadius": "4px",
                "padding": "10px 12px",
                "cursor": "pointer",
            },
        )
        cards.append(card)

    card_grid = html.Div(
        cards,
        style={
            "display": "grid",
            "gridTemplateColumns": "1fr 1fr",
            "gap": "8px",
        },
    )

    # Chips output is hidden but must be a list for the callback
    return [], card_grid


@app.callback(
    Output("terminal-active-symbol", "data"),
    Input({"type": "watchlist-row-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _select_symbol(n_clicks_list):
    if not any(n_clicks_list):
        return dash.no_update
    return ctx.triggered_id["index"]


@app.callback(
    Output("news-feed", "children"),
    Output("news-header", "children"),
    Input("terminal-active-symbol", "data"),
    Input("news-interval", "n_intervals"),
)
def _update_news(symbol, _):
    sym = symbol or (WATCHLIST[0] if WATCHLIST else "AAPL")
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
                    "fontSize": "11px",
                    "fontStyle": "italic",
                    "padding": "8px",
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
                                    "fontSize": "11px",
                                    "fontWeight": "600",
                                    "textDecoration": "none",
                                    "lineHeight": "1.4",
                                    "fontFamily": FONT,
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
                        style={"fontSize": "9px", "color": TEXT_DIM, "fontStyle": "italic"},
                    ),
                ],
                style={
                    "borderLeft": f"3px solid {sent_col}",
                    "background": f"{sent_col}07",
                    "padding": "8px 10px",
                    "marginBottom": "7px",
                    "borderRadius": "0 3px 3px 0",
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
    sym = symbol or (WATCHLIST[0] if WATCHLIST else "AAPL")

    try:
        items = fetch_news(sym)
    except Exception:
        items = []

    if not items:
        return html.Div(
            "No news available.",
            style={
                "color": TEXT_DIM,
                "fontSize": "11px",
                "fontStyle": "italic",
                "padding": "8px",
            },
        )

    cards = []
    for item in items:
        sentiment = item.get("sentiment", "neutral")
        if sentiment == "positive":
            sent_dot = "🟢"
            border_col = "#10b981"
        elif sentiment == "negative":
            sent_dot = "🔴"
            border_col = "#ef4444"
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
            fillcolor=f"rgba({r_c},{g_c},{b_c},0.08)",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[dates[max_idx]],
            y=[closes[max_idx]],
            mode="markers+text",
            marker=dict(color=YELLOW, size=6),
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
            marker=dict(color=RED, size=6),
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
        margin=dict(l=8, r=8, t=28, b=8),
        height=200,
        showlegend=False,
        xaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            tickfont=dict(size=9, color=TEXT_DIM),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            tickfont=dict(size=9, color=TEXT_DIM),
            tickprefix="$",
        ),
    )
    return dcc.Graph(
        figure=fig,
        config={"displayModeBar": False},
        style={"height": "200px"},
    )


@app.callback(
    Output("screener-results", "children"),
    Output("screener-results-store", "data"),
    Output("screener-active-store", "data"),
    Input("btn-screener-run", "n_clicks"),
    State("terminal-watchlist", "data"),
    State("screener-rsi", "value"),
    State("screener-chg-min", "value"),
    State("screener-chg-max", "value"),
    State("screener-flags", "value"),
    prevent_initial_call=True,
)
def _run_screener(_, watchlist, rsi_range, chg_min, chg_max, flags):
    wl = watchlist or []
    if not wl:
        return (
            html.Div(
                "No symbols to screen.",
                style={"color": TEXT_DIM, "fontSize": "11px", "padding": "8px"},
            ),
            [],
            False,
        )

    rsi_min = (rsi_range or [0, 100])[0]
    rsi_max = (rsi_range or [0, 100])[1]

    filters: dict = {"rsi_min": rsi_min, "rsi_max": rsi_max}
    if chg_min is not None:
        try:
            filters["change_pct_min"] = float(chg_min)
        except (TypeError, ValueError):
            pass
    if chg_max is not None:
        try:
            filters["change_pct_max"] = float(chg_max)
        except (TypeError, ValueError):
            pass
    flags = flags or []
    if "above_ma20" in flags:
        filters["above_ma20"] = True
    if "high_volume" in flags:
        filters["volume_min"] = 1_000_000

    try:
        results = run_screener(wl, filters)
    except Exception:
        results = []

    if not results:
        return (
            html.Div(
                "No symbols match the current filters.",
                style={
                    "color": TEXT_DIM,
                    "fontSize": "11px",
                    "fontStyle": "italic",
                    "padding": "8px",
                },
            ),
            [],
            False,
        )

    matched_syms = [item.get("symbol", "") for item in results]
    rows = []
    for item in results:
        sym = item.get("symbol", "")
        rows.append(_watchlist_row(sym, item, False))

    return (
        html.Div(rows, style={"background": BG_HOVER, "borderRadius": "3px", "padding": "4px"}),
        matched_syms,
        True,
    )


@app.callback(
    Output("screener-active-store", "data", allow_duplicate=True),
    Output("screener-results-store", "data", allow_duplicate=True),
    Input("btn-screener-clear", "n_clicks"),
    prevent_initial_call=True,
)
def _clear_screener(_):
    return False, []


@app.callback(
    Output("compare-panel", "style"),
    Input("btn-compare", "n_clicks"),
    State("compare-panel", "style"),
    prevent_initial_call=True,
)
def _toggle_compare(n, style):
    is_open = (style or {}).get("display") != "none"
    if is_open:
        return {"display": "none"}
    return {
        "display": "block",
        "marginBottom": "12px",
        "background": BG_HOVER,
        "border": f"1px solid {BORDER}",
        "borderRadius": "4px",
        "padding": "12px 14px",
    }


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


@app.callback(
    Output("csv-download", "data"),
    Input("btn-export-csv", "n_clicks"),
    State("terminal-watchlist", "data"),
    prevent_initial_call=True,
)
def _export_csv(n, watchlist):
    if not n or not watchlist:
        return dash.no_update
    import csv as _csv
    import io
    from datetime import date as _date

    wl = watchlist or []
    try:
        prices = fetch_watchlist_prices(wl)
    except Exception:
        prices = {}

    rows = []
    for sym in wl:
        d = prices.get(sym, {})
        rows.append(
            {
                "symbol": sym,
                "price": d.get("price", ""),
                "change_pct": d.get("change_pct", ""),
                "rsi_14": d.get("rsi_14", ""),
                "volume": d.get("volume", ""),
                "timestamp": _date.today().isoformat(),
            }
        )

    buf = io.StringIO()
    writer = _csv.DictWriter(
        buf, fieldnames=["symbol", "price", "change_pct", "rsi_14", "volume", "timestamp"]
    )
    writer.writeheader()
    writer.writerows(rows)
    filename = f"apex7_watchlist_{_date.today().isoformat()}.csv"
    return {"content": buf.getvalue(), "filename": filename}


@app.callback(
    Output("price-alerts-store", "data"),
    Input("btn-set-alert", "n_clicks"),
    State("alert-symbol-input", "value"),
    State("alert-direction-dropdown", "value"),
    State("alert-price-input", "value"),
    State("price-alerts-store", "data"),
    prevent_initial_call=True,
)
def _set_alert(_, sym, direction, price, alerts):
    if not sym or price is None:
        return alerts or []
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return alerts or []
    entry = {
        "symbol": sym.strip().upper(),
        "direction": direction or "above",
        "price": price_f,
        "id": int(time.time() * 1000),
    }
    return (alerts or []) + [entry]


@app.callback(
    Output("price-alerts-store", "data", allow_duplicate=True),
    Input({"type": "alert-remove-btn", "index": ALL}, "n_clicks"),
    State("price-alerts-store", "data"),
    prevent_initial_call=True,
)
def _remove_alert(n_clicks_list, alerts):
    if not any(n_clicks_list):
        return alerts or []
    alert_id = ctx.triggered_id["index"]
    return [a for a in (alerts or []) if a.get("id") != alert_id]


@app.callback(
    Output("alerts-list", "children"),
    Output("alert-banner", "children"),
    Output("alert-banner", "style"),
    Input("check-alerts-interval", "n_intervals"),
    State("price-alerts-store", "data"),
    State("terminal-watchlist", "data"),
    prevent_initial_call=False,
)
def _check_alerts(_, alerts, watchlist):
    alerts = alerts or []
    if not alerts:
        empty = html.Div(
            "No alerts set.",
            style={
                "color": TEXT_DIM,
                "fontSize": "11px",
                "fontStyle": "italic",
                "padding": "6px 0",
            },
        )
        return empty, html.Span(), {"display": "none"}

    all_syms = list({a["symbol"] for a in alerts} | set(watchlist or []))
    try:
        prices = fetch_watchlist_prices(all_syms)
    except Exception:
        prices = {}

    triggered = []
    list_items = []
    for a in alerts:
        sym = a["symbol"]
        cur = (prices.get(sym) or {}).get("price")
        fired = False
        if cur is not None:
            if a["direction"] == "above" and cur >= a["price"]:
                fired = True
            elif a["direction"] == "below" and cur <= a["price"]:
                fired = True
        if fired:
            triggered.append(a)

        dir_col = GREEN if a["direction"] == "above" else RED
        # Alert chip: BG_CARD background, YELLOW left border
        list_items.append(
            html.Div(
                [
                    html.Span(
                        sym,
                        style={
                            "fontSize": "10px",
                            "fontWeight": "700",
                            "color": BLUE,
                            "width": "55px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        a["direction"].upper(),
                        style={
                            "fontSize": "9px",
                            "color": dir_col,
                            "width": "45px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        f"${a['price']:.2f}",
                        style={
                            "fontSize": "10px",
                            "color": TEXT_MAIN,
                            "flex": "1",
                        },
                    ),
                    (
                        html.Span(
                            "FIRED",
                            style={"fontSize": "9px", "color": ORANGE, "marginRight": "8px"},
                        )
                        if fired
                        else html.Span()
                    ),
                    html.Button(
                        "×",
                        id={"type": "alert-remove-btn", "index": a["id"]},
                        n_clicks=0,
                        style={
                            "background": "transparent",
                            "border": "none",
                            "color": TEXT_DIM,
                            "cursor": "pointer",
                            "fontSize": "14px",
                            "padding": "0",
                            "fontFamily": FONT,
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "8px",
                    "padding": "5px 8px",
                    "background": BG_CARD,
                    "borderLeft": f"3px solid {YELLOW if fired else BORDER}",
                    "borderRadius": "0 2px 2px 0",
                    "marginBottom": "3px",
                },
            )
        )

    if triggered:
        names = ", ".join(
            f"{a['symbol']} {a['direction'].upper()} ${a['price']:.2f}" for a in triggered[:3]
        )
        banner_children = html.Div(
            [
                html.Span(
                    "ALERT: ", style={"fontWeight": "700", "color": ORANGE, "marginRight": "4px"}
                ),
                html.Span(names, style={"color": TEXT_MAIN}),
            ],
            style={"fontSize": "11px"},
        )
        banner_style = {
            "display": "block",
            "background": f"{ORANGE}18",
            "border": f"1px solid {ORANGE}44",
            "borderRadius": "3px",
            "padding": "7px 10px",
            "marginBottom": "8px",
        }
    else:
        banner_children = html.Span()
        banner_style = {"display": "none"}

    return html.Div(list_items), banner_children, banner_style
