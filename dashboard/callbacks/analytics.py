"""APEX-7 — Analytics tab callback."""

import statistics
from collections import Counter, defaultdict

import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, no_update
from dash.dash_table import DataTable

from dashboard.layout import _load_postmortem, _load_trades_db
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
    _rgba,
    app,
)


def _analytics_postmortem_section(post: list[dict]) -> html.Div:
    """Bloc « Trade postmortem » — colonnes date, symbole, entrée, sortie, P&L, leçon."""
    pm_rows = []
    for pm in post[:12]:
        pnl = float(pm.get("pnl_pct") or 0.0)
        pnl_c = GREEN if pnl >= 0 else RED
        sym = pm.get("symbol") or "—"
        ts_raw = str(pm.get("timestamp") or "")[:19]
        date_s = ts_raw[:10] if len(ts_raw) >= 10 else "—"
        try:
            bp = float(pm.get("buy_price") or 0)
            entry_s = f"{bp:.2f}" if bp > 0 else "—"
        except (TypeError, ValueError):
            entry_s = "—"
        try:
            sp = float(pm.get("sell_price") or 0)
            exit_s = f"{sp:.2f}" if sp > 0 else "—"
        except (TypeError, ValueError):
            exit_s = "—"
        summary_txt = (pm.get("summary") or "")[:160]
        sym_chip = html.Span(
            sym,
            style={
                "fontSize": "9px",
                "fontWeight": "700",
                "color": BLUE,
                "background": f"{BLUE}11",
                "border": f"1px solid {BLUE}33",
                "borderRadius": "2px",
                "padding": "2px 6px",
                "flexShrink": "0",
            },
        )
        pm_rows.append(
            html.Div(
                [
                    html.Span(
                        date_s,
                        style={
                            "fontSize": "10px",
                            "color": TEXT_DIM,
                            "width": "86px",
                            "flexShrink": "0",
                        },
                    ),
                    sym_chip,
                    html.Span(
                        entry_s,
                        style={
                            "fontSize": "10px",
                            "color": TEXT_MAIN,
                            "width": "56px",
                            "flexShrink": "0",
                            "textAlign": "right",
                        },
                    ),
                    html.Span(
                        exit_s,
                        style={
                            "fontSize": "10px",
                            "color": TEXT_MAIN,
                            "width": "56px",
                            "flexShrink": "0",
                            "textAlign": "right",
                        },
                    ),
                    html.Span(
                        f"{pnl:+.1f}%",
                        style={
                            "fontSize": "11px",
                            "color": pnl_c,
                            "fontWeight": "700",
                            "width": "52px",
                            "flexShrink": "0",
                        },
                    ),
                    html.Span(
                        summary_txt,
                        style={
                            "fontSize": "10px",
                            "color": TEXT_DIM,
                            "flex": "1",
                            "overflow": "hidden",
                            "textOverflow": "ellipsis",
                            "whiteSpace": "nowrap",
                            "minWidth": "80px",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "10px",
                    "padding": "7px 12px",
                    "background": BG_CARD,
                    "border": f"1px solid {BORDER}",
                    "borderLeft": f"2px solid {pnl_c}",
                    "borderRadius": "0 3px 3px 0",
                    "marginBottom": "4px",
                },
            )
        )

    hdr = html.Div(
        [
            html.Span(
                "DATE",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": "86px",
                    "flexShrink": "0",
                },
            ),
            html.Span(
                "SYM",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": "72px",
                    "flexShrink": "0",
                },
            ),
            html.Span(
                "ENTRY",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": "56px",
                    "flexShrink": "0",
                    "textAlign": "right",
                },
            ),
            html.Span(
                "EXIT",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": "56px",
                    "flexShrink": "0",
                    "textAlign": "right",
                },
            ),
            html.Span(
                "P&L",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "width": "52px",
                    "flexShrink": "0",
                },
            ),
            html.Span(
                "LESSON",
                style={
                    "fontSize": "9px",
                    "color": TEXT_DIM,
                    "letterSpacing": "0.12em",
                    "flex": "1",
                    "minWidth": "80px",
                },
            ),
        ],
        style={
            "display": "flex",
            "alignItems": "center",
            "gap": "10px",
            "padding": "6px 12px",
            "marginBottom": "4px",
            "borderBottom": f"1px solid {BORDER}",
        },
    )

    body = (
        pm_rows
        if pm_rows
        else [
            html.Div(
                "No post-mortem data yet.",
                style={
                    "color": TEXT_DIM,
                    "fontSize": "11px",
                    "fontStyle": "italic",
                    "padding": "12px",
                },
            )
        ]
    )

    return html.Div(
        [
            html.Div(
                "Trade postmortem",
                style={
                    "fontSize": "9px",
                    "fontWeight": "700",
                    "letterSpacing": "0.18em",
                    "color": TEXT_DIM,
                    "textTransform": "uppercase",
                    "borderBottom": f"1px solid {BORDER}",
                    "paddingBottom": "6px",
                    "marginBottom": "10px",
                    "marginTop": "28px",
                },
            ),
            hdr,
            html.Div(body),
        ]
    )


@app.callback(
    Output("analytics-content", "children"),
    [Input("analytics-tick", "n_intervals"), Input("btn-analytics-refresh", "n_clicks")],
    State("main-tabs", "value"),
    prevent_initial_call=False,
)
def _analytics_refresh(_, __, active_tab):
    if active_tab != "analytics":
        return no_update
    trades = _load_trades_db()
    post = _load_postmortem()
    pm_section = _analytics_postmortem_section(post)

    if not trades:
        return html.Div(
            [
                html.Div(
                    "No trade data yet. Run the agent first.",
                    style={"color": TEXT_DIM, "fontSize": "12px", "padding": "20px"},
                ),
                pm_section,
            ],
            style={"display": "flex", "flexDirection": "column"},
        )

    # ── KPIs ─────────────────────────────────────────────────────────────────
    buys = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]
    total = len(trades)

    # Win rate: for each SELL, find the most recent prior BUY of the same symbol
    pnl_vals: list[float] = []
    for s in sells:
        sym = s.get("symbol")
        sell_price = s.get("price", 0.0)
        sell_ts = s.get("timestamp", "")
        prior_buys = [
            b for b in buys if b.get("symbol") == sym and b.get("timestamp", "") <= sell_ts
        ]
        if prior_buys and sell_price > 0:
            buy_price = prior_buys[-1].get("price", sell_price)
            if buy_price > 0:
                pnl_vals.append((sell_price - buy_price) / buy_price)
    wins = sum(1 for p in pnl_vals if p > 0)
    win_rate = (wins / len(pnl_vals) * 100) if pnl_vals else 0.0
    avg_pnl = statistics.mean(pnl_vals) * 100 if pnl_vals else 0.0
    best_t = max(pnl_vals) if pnl_vals else 0.0
    worst_t = min(pnl_vals) if pnl_vals else 0.0
    confs = [t.get("confidence", 0) for t in trades if t.get("confidence")]
    avg_conf = statistics.mean(confs) if confs else 0.0

    tickers = [t["symbol"] for t in trades if t.get("symbol")]
    fav = max(set(tickers), key=tickers.count) if tickers else "—"

    live_n = sum(1 for t in trades if t.get("source") == "live")
    sim_n = sum(1 for t in trades if t.get("source") == "simulation")
    ratio = f"{sim_n}/{live_n}" if (sim_n + live_n) > 0 else "—"

    kpi_items = [
        ("WIN RATE", f"{win_rate:.1f}%", GREEN if win_rate > 50 else RED),
        ("AVG P&L", f"{avg_pnl:+.2f}%", GREEN if avg_pnl >= 0 else RED),
        ("BEST TRADE", f"{best_t * 100:+.2f}%", GREEN),
        ("WORST TRADE", f"{worst_t * 100:+.2f}%", RED),
        ("TOTAL TRADES", str(total), BLUE),
        ("AVG CONFIDENCE", f"{avg_conf:.0%}", PURPLE),
        ("FAV TICKER", fav, YELLOW),
        ("SIM / LIVE", ratio, ORANGE),
    ]

    kpi_row = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        lbl,
                        style={
                            "fontSize": "9px",
                            "color": TEXT_DIM,
                            "letterSpacing": "0.1em",
                            "marginBottom": "4px",
                        },
                    ),
                    html.Div(val, style={"fontSize": "16px", "fontWeight": "700", "color": col}),
                ],
                style={
                    "background": BG_CARD,
                    "border": f"1px solid {BORDER}",
                    "borderRadius": "4px",
                    "padding": "12px 14px",
                },
            )
            for lbl, val, col in kpi_items
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(8, 1fr)",
            "gap": "8px",
            "marginBottom": "20px",
        },
    )

    # ── CHARTS ───────────────────────────────────────────────────────────────
    _plotly_theme = dict(
        template="plotly_dark",
        paper_bgcolor=BG_DEEP,
        plot_bgcolor=BG_CARD,
        font=dict(family=FONT, color=TEXT_MAIN, size=10),
        margin=dict(l=40, r=20, t=30, b=40),
    )

    # 1. P&L by ticker (bar)
    ticker_pnl: dict[str, float] = defaultdict(float)
    for t in sells:
        sym = t.get("symbol") or "UNK"
        ticker_pnl[sym] += t.get("amount_usd", 0)
    sorted_tickers = sorted(ticker_pnl.items(), key=lambda x: x[1])
    bar_colors = [GREEN if v >= 0 else RED for _, v in sorted_tickers]
    fig1 = go.Figure(
        go.Bar(
            x=[v for _, v in sorted_tickers],
            y=[s for s, _ in sorted_tickers],
            orientation="h",
            marker_color=bar_colors,
        )
    )
    fig1.update_layout(title="P&L by Ticker", height=250, **_plotly_theme)

    # 2. Action distribution (donut)
    action_counts = {
        "BUY": len(buys),
        "SELL": len(sells),
        "HOLD": sum(1 for t in trades if t["action"] == "HOLD"),
    }
    fig2 = go.Figure(
        go.Pie(
            labels=list(action_counts.keys()),
            values=list(action_counts.values()),
            hole=0.6,
            marker_colors=[BLUE, GREEN, GRAY],
            textfont=dict(family=FONT, size=10),
        )
    )
    fig2.update_layout(title="Action Distribution", height=250, **_plotly_theme)

    # 3. Confidence over time (line)
    conf_trades = [t for t in reversed(trades) if t.get("confidence")]
    fig3 = go.Figure(
        go.Scatter(
            x=list(range(len(conf_trades))),
            y=[t["confidence"] for t in conf_trades],
            mode="lines",
            line=dict(color=PURPLE, width=1.5),
            fill="tozeroy",
            fillcolor=_rgba(PURPLE, 0.09),
        )
    )
    fig3.update_layout(title="Confidence Over Time", height=250, **_plotly_theme)

    # 4. Trades by hour
    hours = Counter()
    for t in trades:
        try:
            h = int(t["timestamp"][11:13])
            hours[h] += 1
        except Exception:
            pass
    hour_x = list(range(24))
    hour_y = [hours.get(h, 0) for h in hour_x]
    fig4 = go.Figure(go.Bar(x=hour_x, y=hour_y, marker_color=BLUE))
    fig4.update_layout(title="Trades by Hour", height=250, **_plotly_theme)

    charts_row = html.Div(
        [
            dcc.Graph(figure=fig1, config={"displayModeBar": False}),
            dcc.Graph(figure=fig2, config={"displayModeBar": False}),
            dcc.Graph(figure=fig3, config={"displayModeBar": False}),
            dcc.Graph(figure=fig4, config={"displayModeBar": False}),
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": "1fr 1fr",
            "gap": "12px",
            "marginBottom": "20px",
        },
    )

    # ── DATA TABLE ───────────────────────────────────────────────────────────
    table_cols = [
        {"name": c, "id": c}
        for c in [
            "timestamp",
            "symbol",
            "action",
            "price",
            "amount_usd",
            "confidence",
            "emotion",
            "lesson",
            "source",
        ]
    ]
    table_data = []
    for t in trades:
        row = {
            k: t.get(k, "")
            for k in [
                "timestamp",
                "symbol",
                "action",
                "price",
                "amount_usd",
                "confidence",
                "emotion",
                "lesson",
                "source",
            ]
        }
        row["timestamp"] = str(row["timestamp"])[:19]
        row["price"] = f"{row['price']:.2f}" if isinstance(row["price"], float) else row["price"]
        row["amount_usd"] = (
            f"{row['amount_usd']:.2f}"
            if isinstance(row["amount_usd"], float)
            else row["amount_usd"]
        )
        row["confidence"] = (
            f"{row['confidence']:.0%}"
            if isinstance(row["confidence"], float)
            else row["confidence"]
        )
        table_data.append(row)

    data_table = DataTable(
        columns=table_cols,
        data=table_data,
        page_size=20,
        sort_action="native",
        filter_action="native",
        style_table={
            "background": BG_DEEP,
            "border": f"1px solid {BORDER}",
            "borderRadius": "4px",
            "overflowX": "auto",
        },
        style_header={
            "background": BG_CARD,
            "color": GREEN,
            "fontSize": "10px",
            "fontFamily": FONT,
            "fontWeight": "700",
            "letterSpacing": "0.1em",
            "border": f"1px solid {BORDER}",
        },
        style_cell={
            "background": BG_DEEP,
            "color": TEXT_MAIN,
            "fontSize": "11px",
            "fontFamily": FONT,
            "borderBottom": f"1px solid {BORDER}",
            "padding": "6px 10px",
            "whiteSpace": "normal",
            "textOverflow": "ellipsis",
            "maxWidth": "200px",
        },
        style_data_conditional=[
            {"if": {"filter_query": '{action} = "BUY"'}, "background": f"{BLUE}12"},
            {"if": {"filter_query": '{action} = "SELL"'}, "background": f"{RED}12"},
            {"if": {"filter_query": '{source} = "simulation"'}, "opacity": "0.7"},
        ],
    )

    return html.Div([kpi_row, charts_row, data_table, pm_section])
