"""APEX-7 — Terminal tab callbacks (13 callbacks)."""

import time

import dash
import plotly.graph_objects as go
from dash import Input, Output, State, ctx, html, MATCH

from config import WATCHLIST
from market_data import (
    fetch_comparison,
    fetch_macro,
    fetch_news,
    fetch_sparkline,
    fetch_watchlist_prices,
    run_screener,
)
from dashboard.layout import _watchlist_row
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
    app,
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
        d = data.get(key, {})
        price = d.get("price")
        chg = d.get("change_pct")
        dirn = d.get("direction", "flat")

        if price is None:
            price_str = "—"
        else:
            price_str = f"{float(price):.2f}"

        if chg is None:
            chg_str = "—"
            chg_col = TEXT_DIM
            arrow = ""
        else:
            chg_f = float(chg)
            chg_col = GREEN if dirn == "up" else (RED if dirn == "down" else TEXT_DIM)
            arrow = "▲ " if dirn == "up" else ("▼ " if dirn == "down" else "")
            chg_str = f"{arrow}{chg_f:+.2f}%"

        blocs.append(
            html.Div(
                [
                    html.Span(
                        key,
                        style={
                            "fontSize": "9px",
                            "color": TEXT_DIM,
                            "letterSpacing": "0.12em",
                            "marginRight": "8px",
                            "fontWeight": "700",
                        },
                    ),
                    html.Span(
                        price_str,
                        style={
                            "fontSize": "13px",
                            "fontWeight": "700",
                            "color": TEXT_MAIN,
                            "marginRight": "6px",
                        },
                    ),
                    html.Span(
                        chg_str,
                        style={
                            "fontSize": "11px",
                            "color": chg_col,
                            "fontWeight": "600",
                        },
                    ),
                ],
                style={"display": "flex", "alignItems": "center"},
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
    Input({"type": "watchlist-remove", "index": MATCH}, "n_clicks"),
    State("terminal-watchlist", "data"),
    prevent_initial_call=True,
)
def _remove_symbol(_, watchlist):
    sym = ctx.triggered_id["index"]
    wl = [s for s in (watchlist or []) if s != sym]
    return wl


@app.callback(
    Output("watchlist-chips", "children"),
    Output("watchlist-table", "children"),
    Input("terminal-watchlist", "data"),
    Input("watchlist-interval", "n_intervals"),
    Input("terminal-active-symbol", "data"),
)
def _update_watchlist(watchlist, _, active_sym):
    wl = watchlist or []
    if not wl:
        chips = []
        table = html.Div(
            "No symbols. Add one above.",
            style={
                "color": TEXT_DIM,
                "fontSize": "11px",
                "fontStyle": "italic",
                "padding": "10px",
            },
        )
        return chips, table

    try:
        prices = fetch_watchlist_prices(wl)
    except Exception:
        prices = {}

    chips = []
    for sym in wl:
        d = prices.get(sym, {})
        chg = d.get("change_pct", 0.0) or 0.0
        dot_col = GREEN if chg >= 0 else RED
        is_active = sym == active_sym
        chip_border = "1px solid #ffffff" if is_active else f"1px solid {BORDER}"
        chips.append(
            html.Div(
                [
                    html.Span(
                        "●", style={"color": dot_col, "marginRight": "4px", "fontSize": "9px"}
                    ),
                    html.Span(
                        sym, style={"fontSize": "10px", "fontWeight": "700", "color": TEXT_MAIN}
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
                            "fontSize": "12px",
                            "padding": "0 0 0 4px",
                            "lineHeight": "1",
                            "fontFamily": FONT,
                        },
                    ),
                ],
                style={
                    "display": "inline-flex",
                    "alignItems": "center",
                    "background": BG_DEEP,
                    "border": chip_border,
                    "borderRadius": "3px",
                    "padding": "3px 6px",
                },
            )
        )

    rows = []
    for sym in wl:
        d = prices.get(sym, {})
        try:
            spark = fetch_sparkline(sym)
        except Exception:
            spark = []
        rows.append(_watchlist_row(sym, d, sym == active_sym, spark))

    return chips, html.Div(rows)


@app.callback(
    Output("terminal-active-symbol", "data"),
    Input({"type": "watchlist-row-btn", "index": MATCH}, "n_clicks"),
    prevent_initial_call=True,
)
def _select_symbol(_):
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
    Output("screener-results", "children"),
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
        return html.Div(
            "No symbols to screen.", style={"color": TEXT_DIM, "fontSize": "11px", "padding": "8px"}
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
        return html.Div(
            "No symbols match the current filters.",
            style={
                "color": TEXT_DIM,
                "fontSize": "11px",
                "fontStyle": "italic",
                "padding": "8px",
            },
        )

    rows = []
    for item in results:
        sym = item.get("symbol", "")
        rows.append(_watchlist_row(sym, item, False))

    return html.Div(rows, style={"background": BG_HOVER, "borderRadius": "3px", "padding": "4px"})


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
    Input({"type": "alert-remove-btn", "index": MATCH}, "n_clicks"),
    State("price-alerts-store", "data"),
    prevent_initial_call=True,
)
def _remove_alert(_, alerts):
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
                    "background": f"{ORANGE}0a" if fired else "transparent",
                    "border": f"1px solid {ORANGE}44" if fired else f"1px solid {BORDER}22",
                    "borderRadius": "2px",
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
